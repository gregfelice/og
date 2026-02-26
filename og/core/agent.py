"""Agent loop: message → LLM → tool → respond → persist."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import AsyncIterator

import anthropic

from og.config.schema import Config
from og.core.budget import BudgetTracker
from og.core.context import ContextBuilder
from og.core.tools import ToolRegistry, ToolResult
from og.memory.embeddings import EmbeddingClient
from og.memory.manager import Memory
from og.memory.pg import PgMemory
from og.session.store import SessionStore
from og.skills.loader import SkillRegistry

logger = logging.getLogger(__name__)


class Agent:
    """Main agent runtime — orchestrates the LLM ↔ tool loop."""

    def __init__(
        self,
        config: Config,
        memory: Memory | PgMemory,
        session_store: SessionStore | None = None,
        budget: BudgetTracker | None = None,
        pool=None,
    ):
        self.config = config
        self.client = anthropic.AsyncAnthropic()
        self.tools = ToolRegistry(bash_timeout=config.tools.bash_timeout)
        self.memory = memory
        self.pool = pool
        self.compact_hook = None
        self._user_message_count = 0

        # Use provided backends or create flat-file defaults
        self.session_store = session_store or SessionStore(config.session.storage_dir)
        self.budget = budget or BudgetTracker(
            budget_limit=config.llm.budget_limit,
            ledger_path=Path.home() / ".og" / "budget.jsonl",
        )

        # Discover skills from bundled + configured dirs
        skill_dirs = [Path("skills")]
        if config.skills.dirs:
            skill_dirs.extend(config.skills.dirs)
        self.skill_registry = SkillRegistry(skill_dirs if config.skills.enabled else None)

        self.context_builder = ContextBuilder(
            prompts_dir=config.prompts_dir,
            memory=self.memory,
            skill_registry=self.skill_registry,
        )

    @classmethod
    async def create(cls, config: Config) -> Agent:
        """Async factory: tries PostgreSQL backends, falls back to flat-file."""
        pool = None
        memory: Memory | PgMemory
        session_store = None
        budget = None

        try:
            import asyncpg
            from pgvector.asyncpg import register_vector

            from og.core.pg_budget import PgBudgetTracker
            from og.session.pg import PgSessionStore

            pool = await asyncpg.create_pool(
                dsn=config.db.dsn,
                min_size=config.db.min_pool,
                max_size=config.db.max_pool,
                init=lambda conn: register_vector(conn),
            )
            embedder = EmbeddingClient(
                base_url=config.embedding.ollama_base_url,
                model=config.embedding.model,
            )
            # Quick connectivity check: embed a test string
            await embedder.embed("connection test")

            project_id = config.memory.project_id

            memory = PgMemory(
                pool=pool,
                embedder=embedder,
                project_id=project_id,
            )
            session_store = PgSessionStore(pool=pool, project_id=project_id)
            budget = PgBudgetTracker(
                pool=pool,
                project_id=project_id,
                budget_limit=config.llm.budget_limit,
            )
            logger.info("Using PostgreSQL backends (memory, sessions, budget)")

            # Phase 3: try to set up knowledge graph
            try:
                from og.knowledge.extractor import KnowledgeExtractor
                from og.knowledge.graph import KnowledgeGraph
                from og.knowledge.hooks import PreCompactHook

                graph = KnowledgeGraph(pool=pool, project_id=project_id)
                extractor = KnowledgeExtractor()
                compact_hook = PreCompactHook(
                    pool=pool,
                    embedder=embedder,
                    extractor=extractor,
                    graph=graph,
                    project_id=project_id,
                )
                memory = PgMemory(
                    pool=pool,
                    embedder=embedder,
                    project_id=project_id,
                    graph=graph,
                )
                agent = cls(
                    config=config,
                    memory=memory,
                    session_store=session_store,
                    budget=budget,
                    pool=pool,
                )
                agent.compact_hook = compact_hook
                logger.info("Knowledge graph enabled")
                return agent
            except Exception as e:
                logger.debug("Knowledge graph not available: %s", e)
                # Fall through to return agent without graph
        except Exception as e:
            logger.warning("DB unavailable, using flat-file backends: %s", e)
            if pool is not None:
                await pool.close()
                pool = None
            memory = Memory(
                storage_dir=config.memory.storage_dir,
                memory_file=config.memory.memory_file,
                daily_dir=config.memory.daily_logs_dir,
            )

        return cls(
            config=config,
            memory=memory,
            session_store=session_store,
            budget=budget,
            pool=pool,
        )

    async def run(self, message: str, session_id: str) -> str:
        """Execute the full agent loop for a single user message."""
        await self.budget.check()

        # Load existing session
        events = await self.session_store.load(session_id)
        if not events:
            await self.session_store.append(session_id, {"type": "session_start"})

        # Record user message
        await self.session_store.append(session_id, {"type": "user_message", "content": message})
        self._user_message_count += 1

        # Build system prompt with matched skills
        matched_skills = self.skill_registry.match(message)
        system_prompt = await self.context_builder.build(message, matched_skills)

        # Reconstruct message history from events
        all_events = await self.session_store.load(session_id)
        messages = self.session_store.to_messages(all_events)

        # Run the LLM ↔ tool loop
        final_text = await self._loop(system_prompt, messages, session_id)

        # Log to memory
        await self.memory.log(message, final_text)

        # Maybe extract knowledge
        await self._maybe_extract_knowledge(session_id, messages)

        return final_text

    async def run_stream(self, message: str, session_id: str) -> AsyncIterator[str]:
        """Execute the agent loop, yielding text deltas as they stream in."""
        await self.budget.check()

        events = await self.session_store.load(session_id)
        if not events:
            await self.session_store.append(session_id, {"type": "session_start"})

        await self.session_store.append(session_id, {"type": "user_message", "content": message})
        self._user_message_count += 1

        matched_skills = self.skill_registry.match(message)
        system_prompt = await self.context_builder.build(message, matched_skills)

        all_events = await self.session_store.load(session_id)
        messages = self.session_store.to_messages(all_events)

        final_text = ""
        async for chunk in self._loop_stream(system_prompt, messages, session_id):
            final_text += chunk
            yield chunk

        await self.memory.log(message, final_text)
        await self._maybe_extract_knowledge(session_id, messages)

    async def _record_usage(self, usage, session_id: str = "") -> None:
        """Record token usage from an API response."""
        await self.budget.record(
            model=self.config.llm.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            session_id=session_id,
        )

    async def _maybe_extract_knowledge(self, session_id: str, messages: list[dict]) -> None:
        """Trigger knowledge extraction every 20 user messages."""
        if self.compact_hook is None:
            return
        if self._user_message_count % 20 != 0:
            return

        try:
            # Build conversation text from recent messages
            text_parts = []
            for msg in messages[-40:]:  # Last ~20 exchanges
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    text_parts.append(f"{role}: {content}")
            conversation_text = "\n".join(text_parts)
            if conversation_text:
                count = await self.compact_hook.run(session_id, conversation_text)
                if count:
                    logger.info("Extracted %d knowledge chunks from session %s", count, session_id)
        except Exception:
            logger.warning("Knowledge extraction failed", exc_info=True)

    async def _loop(self, system: str, messages: list[dict], session_id: str) -> str:
        """Core loop: call LLM, execute tools, repeat until text-only response."""
        tool_schemas = ToolRegistry.get_tool_schemas()

        while True:
            await self.budget.check()

            response = await self.client.messages.create(
                model=self.config.llm.model,
                max_tokens=self.config.llm.max_tokens,
                system=system,
                messages=messages,
                tools=tool_schemas,
            )
            await self._record_usage(response.usage, session_id)

            # Collect text and tool_use blocks
            text_parts = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            full_text = "\n".join(text_parts)

            if not tool_uses:
                # No tools — final response
                await self.session_store.append(
                    session_id,
                    {
                        "type": "assistant_message",
                        "content": full_text,
                    },
                )
                return full_text

            # Persist assistant message with tool_use blocks
            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tu in tool_uses:
                await self.session_store.append(
                    session_id,
                    {
                        "type": "tool_use",
                        "tool_use_id": tu.id,
                        "name": tu.name,
                        "input": tu.input,
                    },
                )
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tu.id,
                        "name": tu.name,
                        "input": tu.input,
                    }
                )

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and build results
            tool_results_content = []
            for tu in tool_uses:
                result: ToolResult = await self.tools.execute(tu.name, tu.input)
                content = (
                    result.output if result.success else f"Error: {result.error}\n{result.output}"
                )
                await self.session_store.append(
                    session_id,
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": content,
                        "is_error": not result.success,
                    },
                )
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": content,
                        "is_error": not result.success,
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

    async def _loop_stream(
        self, system: str, messages: list[dict], session_id: str
    ) -> AsyncIterator[str]:
        """Streaming variant of the core loop."""
        tool_schemas = ToolRegistry.get_tool_schemas()

        while True:
            await self.budget.check()

            # Stream the response
            text_parts = []
            tool_uses = []
            current_tool_input = {}
            async with self.client.messages.stream(
                model=self.config.llm.model,
                max_tokens=self.config.llm.max_tokens,
                system=system,
                messages=messages,
                tools=tool_schemas,
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool_input = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "input_json": "",
                            }
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            text_parts.append(event.delta.text)
                            yield event.delta.text
                        elif event.delta.type == "input_json_delta":
                            if current_tool_input:
                                current_tool_input["input_json"] += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if current_tool_input and current_tool_input.get("input_json") is not None:
                            try:
                                parsed_input = json.loads(current_tool_input["input_json"])
                            except json.JSONDecodeError:
                                parsed_input = {}
                            tool_uses.append(
                                {
                                    "id": current_tool_input["id"],
                                    "name": current_tool_input["name"],
                                    "input": parsed_input,
                                }
                            )
                            current_tool_input = {}
                # Get final message for usage stats
                final_message = await stream.get_final_message()
                await self._record_usage(final_message.usage, session_id)

            full_text = "".join(text_parts)

            if not tool_uses:
                await self.session_store.append(
                    session_id,
                    {
                        "type": "assistant_message",
                        "content": full_text,
                    },
                )
                return

            # Persist and execute tools (same as non-streaming)
            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})

            for tu in tool_uses:
                await self.session_store.append(
                    session_id,
                    {
                        "type": "tool_use",
                        "tool_use_id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    },
                )
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                )

            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content = []
            for tu in tool_uses:
                result = await self.tools.execute(tu["name"], tu["input"])
                content = (
                    result.output if result.success else f"Error: {result.error}\n{result.output}"
                )

                yield f"\n\n**[Tool: {tu['name']}]** {'OK' if result.success else 'Error'}\n\n"

                await self.session_store.append(
                    session_id,
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": content,
                        "is_error": not result.success,
                    },
                )
                tool_results_content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": content,
                        "is_error": not result.success,
                    }
                )

            messages.append({"role": "user", "content": tool_results_content})

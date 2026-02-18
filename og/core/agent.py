"""Agent loop: message → LLM → tool → respond → persist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

import anthropic

from og.config.schema import Config
from og.core.budget import BudgetTracker
from og.core.context import ContextBuilder
from og.core.tools import ToolRegistry, ToolResult
from og.memory.manager import Memory
from og.session.store import SessionStore
from og.skills.loader import SkillRegistry


class Agent:
    """Main agent runtime — orchestrates the LLM ↔ tool loop."""

    def __init__(self, config: Config):
        self.config = config
        self.client = anthropic.AsyncAnthropic()
        self.tools = ToolRegistry(bash_timeout=config.tools.bash_timeout)
        self.session_store = SessionStore(config.session.storage_dir)
        self.memory = Memory(
            storage_dir=config.memory.storage_dir,
            memory_file=config.memory.memory_file,
            daily_dir=config.memory.daily_logs_dir,
        )
        self.budget = BudgetTracker(
            budget_limit=config.llm.budget_limit,
            ledger_path=Path.home() / ".og" / "budget.jsonl",
        )

        # Discover skills from bundled + configured dirs
        skill_dirs = [Path("skills")]
        if config.skills.dirs:
            skill_dirs.extend(config.skills.dirs)
        self.skill_registry = SkillRegistry(
            skill_dirs if config.skills.enabled else None
        )

        self.context_builder = ContextBuilder(
            prompts_dir=config.prompts_dir,
            memory=self.memory,
            skill_registry=self.skill_registry,
        )

    async def run(self, message: str, session_id: str) -> str:
        """Execute the full agent loop for a single user message."""
        self.budget.check()

        # Load existing session
        events = self.session_store.load(session_id)
        if not events:
            self.session_store.append(session_id, {"type": "session_start"})

        # Record user message
        self.session_store.append(session_id, {"type": "user_message", "content": message})

        # Build system prompt with matched skills
        matched_skills = self.skill_registry.match(message)
        system_prompt = self.context_builder.build(message, matched_skills)

        # Reconstruct message history from events
        all_events = self.session_store.load(session_id)
        messages = self.session_store.to_messages(all_events)

        # Run the LLM ↔ tool loop
        final_text = await self._loop(system_prompt, messages, session_id)

        # Log to memory
        self.memory.log(message, final_text)

        return final_text

    async def run_stream(
        self, message: str, session_id: str
    ) -> AsyncIterator[str]:
        """Execute the agent loop, yielding text deltas as they stream in."""
        self.budget.check()

        events = self.session_store.load(session_id)
        if not events:
            self.session_store.append(session_id, {"type": "session_start"})

        self.session_store.append(session_id, {"type": "user_message", "content": message})

        matched_skills = self.skill_registry.match(message)
        system_prompt = self.context_builder.build(message, matched_skills)

        all_events = self.session_store.load(session_id)
        messages = self.session_store.to_messages(all_events)

        final_text = ""
        async for chunk in self._loop_stream(system_prompt, messages, session_id):
            final_text += chunk
            yield chunk

        self.memory.log(message, final_text)

    def _record_usage(self, usage) -> None:
        """Record token usage from an API response."""
        self.budget.record(
            model=self.config.llm.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    async def _loop(self, system: str, messages: list[dict], session_id: str) -> str:
        """Core loop: call LLM, execute tools, repeat until text-only response."""
        tool_schemas = ToolRegistry.get_tool_schemas()

        while True:
            self.budget.check()

            response = await self.client.messages.create(
                model=self.config.llm.model,
                max_tokens=self.config.llm.max_tokens,
                system=system,
                messages=messages,
                tools=tool_schemas,
            )
            self._record_usage(response.usage)

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
                self.session_store.append(session_id, {
                    "type": "assistant_message",
                    "content": full_text,
                })
                return full_text

            # Persist assistant message with tool_use blocks
            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})
            for tu in tool_uses:
                self.session_store.append(session_id, {
                    "type": "tool_use",
                    "tool_use_id": tu.id,
                    "name": tu.name,
                    "input": tu.input,
                })
                assistant_content.append({
                    "type": "tool_use",
                    "id": tu.id,
                    "name": tu.name,
                    "input": tu.input,
                })

            messages.append({"role": "assistant", "content": assistant_content})

            # Execute tools and build results
            tool_results_content = []
            for tu in tool_uses:
                result: ToolResult = await self.tools.execute(tu.name, tu.input)
                content = result.output if result.success else f"Error: {result.error}\n{result.output}"
                self.session_store.append(session_id, {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": not result.success,
                })
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": not result.success,
                })

            messages.append({"role": "user", "content": tool_results_content})

    async def _loop_stream(
        self, system: str, messages: list[dict], session_id: str
    ) -> AsyncIterator[str]:
        """Streaming variant of the core loop."""
        tool_schemas = ToolRegistry.get_tool_schemas()

        while True:
            self.budget.check()

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
                            tool_uses.append({
                                "id": current_tool_input["id"],
                                "name": current_tool_input["name"],
                                "input": parsed_input,
                            })
                            current_tool_input = {}
                # Get final message for usage stats
                final_message = await stream.get_final_message()
                self._record_usage(final_message.usage)

            full_text = "".join(text_parts)

            if not tool_uses:
                self.session_store.append(session_id, {
                    "type": "assistant_message",
                    "content": full_text,
                })
                return

            # Persist and execute tools (same as non-streaming)
            assistant_content = []
            if full_text:
                assistant_content.append({"type": "text", "text": full_text})

            for tu in tool_uses:
                self.session_store.append(session_id, {
                    "type": "tool_use",
                    "tool_use_id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                })
                assistant_content.append({
                    "type": "tool_use",
                    "id": tu["id"],
                    "name": tu["name"],
                    "input": tu["input"],
                })

            messages.append({"role": "assistant", "content": assistant_content})

            tool_results_content = []
            for tu in tool_uses:
                result = await self.tools.execute(tu["name"], tu["input"])
                content = result.output if result.success else f"Error: {result.error}\n{result.output}"

                yield f"\n\n**[Tool: {tu['name']}]** {'OK' if result.success else 'Error'}\n\n"

                self.session_store.append(session_id, {
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": content,
                    "is_error": not result.success,
                })
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": content,
                    "is_error": not result.success,
                })

            messages.append({"role": "user", "content": tool_results_content})

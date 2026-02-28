# OG

Python CLI agent replicating core OpenClaw patterns: agent loop, multi-tool support, session persistence, memory, skill-based extensibility, and budget tracking on PostgreSQL 16 with pgvector + Apache AGE.

## Quick Reference

```bash
# Setup
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# Database setup (PostgreSQL 16 on localhost:5432, requires pgvector + AGE extensions)
python scripts/setup-db.py           # create database, tables, indexes, graph
python scripts/setup-db.py --check   # verify setup
python scripts/setup-db.py --drop    # drop and recreate

# Run
og                                    # interactive REPL
og "do something"                     # one-shot
og --session my-project "message"     # named session
og --model claude-opus-4-6 "message"  # override model

# Lint
ruff check og/
ruff format og/

# Test (pytest + pytest-asyncio configured, no tests yet)
pytest -v --asyncio-mode=auto
```

## Architecture

**Agent loop** (`og/core/agent.py`): async event loop -- user message -> layered system prompt -> Anthropic streaming API -> tool execution -> persist events -> repeat. Budget checked before every LLM call.

**Tools** (`og/core/tools.py`): four async tools -- `read`, `write`, `edit` (exact-match search-and-replace), `bash` (with timeout). All return `ToolResult(output, error)`.

**Layered system prompt** (`og/core/context.py`): composed from `prompts/AGENTS.md` (identity) -> `prompts/SOUL.md` (behavior) -> `prompts/TOOLS.md` (tool reference) -> skill catalog (always) -> active skills (selectively injected when triggers match) -> memory context.

**Skills** (`og/skills/loader.py`): markdown files with YAML frontmatter defining `name`, `triggers`, `description`. Discovered via recursive glob for `SKILL.md` in `skills/` and configured dirs. Trigger matching is case-insensitive substring. Bundled skills: `commit`, `debug`, `research`, `list-skills`.

**Sessions** (`og/session/store.py`): JSONL append-only event logs at `~/.og/sessions/{id}.jsonl`. Event types: `session_start`, `user_message`, `assistant_message`, `tool_use`, `tool_result`. Full history reconstructed from events each turn.

**Memory** (`og/memory/manager.py`): `~/.og/memory/MEMORY.md` (facts) + `~/.og/memory/daily/{date}.md` (logs). Keyword search across MEMORY.md + last 7 days. No vector DB -- flat files + string matching.

**Budget** (`og/core/budget.py`): hardcoded pricing table, ledger at `~/.og/budget.jsonl`, raises `BudgetExceeded` when cap hit.

**Channels** (`og/channels/`): abstract `Channel` base class; `CLIChannel` uses Rich for terminal output. Same Agent can serve different frontends.

## Conventions

- **Language:** Python 3.11+, async throughout (including file I/O via `aiofiles`).
- **Linting:** Ruff with 100-char line length (configured in `pyproject.toml`).
- **Config:** Pydantic BaseSettings with `OG_` prefix and `__` nesting delimiter. Loads from `.env` in project root. Key env vars: `ANTHROPIC_API_KEY` (required), `OG_LLM__MODEL`, `OG_LLM__BUDGET_LIMIT` (default $5), `OG_TOOLS__BASH_TIMEOUT`, `OG_SKILLS__DIRS`, `OG_DB__HOST`, `OG_DB__PORT`, `OG_DB__NAME`, `OG_DB__USER`, `OG_DB__PASSWORD`, `OG_EMBEDDING__MODEL`, `OG_EMBEDDING__OLLAMA_BASE_URL`.
- **Context store:** PostgreSQL 16 with pgvector (HNSW semantic search) + Apache AGE (knowledge graph) + tsvector (keyword search). Setup via `scripts/setup-db.py`. Embeddings via `mxbai-embed-large` (1024 dims) on local Ollama (`localhost:11434`). Flat-file fallback remains for sessions/memory/budget when DB is unavailable.
- **Streaming** is the primary UX path (`run_stream()` yields text deltas).
- **Skills** are markdown-driven and human-editable. To add a skill: create `skills/{name}/SKILL.md` with frontmatter (`name`, `triggers`, `description`) and markdown body.
- **ADRs** go in `docs/adr/`. **Research** goes in `docs/research/`.

## Key Documentation

| Document | Path | Description |
|---|---|---|
| README | `README.md` | Learning report, architecture overview, integration ideas |
| Backlog | `docs/BACKLOG.md` | P0-P3 prioritized engineering backlog |
| ADR-001 | `docs/adr/001-context-management-pgvector-age.md` | Context management with pgvector + AGE |
| Research | `docs/research/2026-02-25-context-management-pgvector-age.md` | pgvector + AGE research and design notes |
| System prompts | `prompts/AGENTS.md`, `prompts/SOUL.md`, `prompts/TOOLS.md` | Layered system prompt sources |
| DB setup | `scripts/setup-db.py` | PostgreSQL schema, extensions, graph creation |

## Status

**Phase 3-4: Knowledge Graph + MCP Server**

- **P0 (critical):** Stabilize knowledge extraction pipeline (AGE extension loading, asyncpg params, pgvector type casting); validate pre-compact hook against real Claude Code transcripts.
- **P1 (next):** Complete MCP server exposing `context_recall` tool; add tests for agent loop, tools, skill matching, retrieval quality.
- **P2 (soon):** Session start injection, knowledge deduplication, operational runbook, multi-project context isolation.
- **P3 (future):** Slack/Discord channel, web UI, skill authoring guide, latency targets, Ollama model fallback chain.

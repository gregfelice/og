# OG — Engineering Backlog

## Current Phase: Phase 3-4 (Knowledge Graph + MCP Server)

## P0 — Critical

- [ ] Stabilize Phase 3 knowledge extraction pipeline (PG layer bugs in AGE extension loading, asyncpg params, pgvector type casting)
- [ ] Validate pre-compact hook against real Claude Code transcripts — confirm knowledge survives compaction

## P1 — Next Sprint

- [ ] Complete Phase 4 MCP server — expose `context_recall` tool for Claude Code sessions
- [ ] Add tests (agent loop, tool execution, skill matching, retrieval quality)
- [ ] Measure retrieval quality: >70% of queries return relevant context in top-3 results

## P2 — Soon

- [ ] Session start injection — plumb retrieved context into Claude Code session start hook
- [ ] Knowledge deduplication improvements (detect contradictions, handle superseded facts)
- [ ] Operational runbook (PostgreSQL maintenance, embedding re-indexing, knowledge compaction)
- [ ] Multi-project context isolation (per-project graphs vs shared knowledge)

## P3 — Future

- [ ] Slack/Discord channel implementation (reuse Channel abstraction)
- [ ] Web UI channel
- [ ] Skill authoring guide and community skill format
- [ ] Latency targets: <200ms for context recall, <500ms for knowledge extraction
- [ ] Ollama model fallback chain (mxbai-embed-large → nomic-embed-text → OpenAI)

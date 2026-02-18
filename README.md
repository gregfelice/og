# OG — OpenClaw Python Experiment - Learning Report

A working Python CLI agent that replicates the core architectural patterns from [OpenClaw](https://openclaw.ai/) (the open-source AI assistant with 60k+ GitHub stars). The goal was to understand those patterns by implementing them in miniature — not just reading about them, but running them against real files on a local machine.

## What did we build, and what did we achieve?

**A functional agent in ~800 lines of Python** that demonstrates every key OpenClaw pattern:

| Pattern | Status | What We Proved |
|---|---|---|
| **Agent Loop** | Working | LLM calls tools, we execute them, feed results back, loop until done. The LLM decides when it's finished. |
| **Pi Agent (4 tools)** | Working | read/write/edit/bash is sufficient for a surprisingly capable agent. The agent read its own source code and explained it. |
| **Layered System Prompt** | Working | AGENTS.md + SOUL.md + TOOLS.md compose at runtime. Personality and capabilities defined in markdown, not code. |
| **Selective Skill Injection** | Working | Skills only inject when triggered. Asking "what skills?" without triggers got a generic answer; after adding the catalog + meta-skill, it gave a complete response. |
| **Session Persistence** | Working | JSONL event log means conversations survive across invocations. Every tool call, every result, persisted. |
| **Memory** | Working | MEMORY.md + daily logs give the agent long-term recall across sessions. |
| **Budget Tracking** | Working | Token-level cost tracking with a hard $5 cap. After 4 real API calls exercising tools and skills: $0.07 spent. |
| **Channel Abstraction** | Working | CLI is just one adapter. The same Agent class could serve Slack, Discord, or a web UI. |

### Key Insights

1. **The agent loop is the real magic.** The LLM isn't just answering questions — it's *deciding what tools to call, in what order, and when to stop*. When we asked it to commit files, it autonomously ran `git init`, created `.gitignore`, staged files, and proposed a commit message — a multi-step workflow from a single sentence.

2. **Skills as documents, not code.** The commit skill is a markdown file. No Python. No function decorators. Just instructions the LLM follows. This means non-engineers can author new agent behaviors.

3. **Haiku is plenty.** Every demo ran on `claude-haiku-4-5` at ~$0.004–0.05 per interaction. Tool use, code comprehension, multi-step reasoning — all worked. You don't need Opus for agentic workflows.

4. **Selective injection matters for cost.** Only loading relevant skills into the system prompt keeps token counts (and costs) down. The full catalog is a few lines; full skill instructions only load when needed.

## Architecture

```
og/
├── og/
│   ├── __main__.py          # CLI entry point (Click)
│   ├── core/
│   │   ├── agent.py          # Agent loop: msg → LLM → tool → respond → persist
│   │   ├── context.py        # Layered prompt builder
│   │   ├── tools.py          # Pi agent's 4 tools: read, write, edit, bash
│   │   └── budget.py         # Token cost tracking with spending cap
│   ├── config/
│   │   └── schema.py         # Pydantic config with env var support
│   ├── skills/
│   │   └── loader.py         # YAML frontmatter parser, trigger matching
│   ├── channels/
│   │   ├── base.py           # Abstract channel interface
│   │   └── cli.py            # Rich terminal adapter
│   ├── session/
│   │   └── store.py          # JSONL append-only event log
│   └── memory/
│       └── manager.py        # MEMORY.md + daily logs + keyword search
├── skills/                    # Bundled skills (markdown-defined behaviors)
│   ├── commit/SKILL.md
│   ├── debug/SKILL.md
│   ├── research/SKILL.md
│   └── list-skills/SKILL.md
└── prompts/                   # Layered system prompt sources
    ├── AGENTS.md              # Identity + capabilities
    ├── SOUL.md                # Behavioral guidelines
    └── TOOLS.md               # Tool descriptions
```

---

## How might we use these capabilities to augment Claude Code?

The goal is not to replace Claude Code but to fill gaps it doesn't cover natively.

**1. Skills as a CLAUDE.md Preprocessor**

Claude Code reads `CLAUDE.md` but it's static. OG's skill loader could dynamically compose `CLAUDE.md` based on context — git branch, recent files, matched skills. Run it as a git hook or alias so Claude Code always starts with project-aware instructions.

**2. Budget Tracking Across Sessions**

Claude Code doesn't expose per-project cost tracking. OG's budget tracker could parse Claude Code's session transcripts (JSONL in `.claude/projects/`), extract token usage per session/project/day, and enforce soft budgets.

**3. MCP Server for Persistent Memory**

Claude Code supports MCP (Model Context Protocol) servers. An OG memory MCP server could expose `memory_search`, `memory_save`, `memory_log`, and `memory_recall` tools that Claude Code calls natively during conversation — real-time, bidirectional memory without workflow changes.

**4. Cheap Delegation via Sub-Agent**

OG running Haiku at $0.004/call handles routine work that doesn't need Opus: triaging files, bulk operations, monitoring builds. Invoke from Claude Code or shell: `og "scan tests/ and list all failing test names"`.

**5. Skill Authoring for Teams**

Maintain a `skills/` directory per project repo with markdown-defined procedures (deploy, migrate, review). These work with OG directly and double as human-readable documentation.

**6. Session Analytics**

OG's JSONL event store provides structured data about agent behavior — tool usage patterns, loop counts per task, recurring workflows — applicable to Claude Code's transcripts as well.

---

## Is there a real-time vector database at work here to store memories?

No. OG's memory system is **flat files and string matching** — nothing more.

```
~/.og/memory/
├── MEMORY.md              # plain text, one fact per line
└── daily/
    └── 2026-02-18.md      # conversation log, appended throughout the day
```

The `search()` method splits the query into words and scans each line for matches. No embeddings, no vector store, no similarity search.

**For the scale we're at, this is fine.** A few hundred facts and a month of daily logs — keyword search is instant and good enough. A vector store becomes necessary when:

- Memory grows to thousands of entries and keyword search misses semantic connections ("deploy" doesn't match a fact about "pushing to production")
- You want "fuzzy recall" — finding relevant context when the user's phrasing doesn't share exact words with the stored fact

The interface (`search(query) -> list[str]`) wouldn't change — you'd just swap the implementation from keyword matching to embedding lookup.

---

## What projects are combining OpenClaw with vector databases to enable similarity search?

### How OpenClaw Handles Memory

OpenClaw itself already solved this. It stores memories as **plain Markdown files** (not opaque vector databases) and layers **hybrid BM25 + vector search** on top:

- **BM25 (full-text search):** Handles exact keyword matches — the "needle in a haystack" case.
- **Vector embeddings:** Handles semantic similarity — "deploy" matches a fact about "pushing to production".
- **Default weighting:** 70% vector / 30% BM25.
- **Local embedding:** Runs via `node-llama-cpp` with auto-downloaded GGUF models. No external API needed.
- **Temporal decay:** Recent memories rank higher; old ones fade via exponential multiplier.
- **MMR (Maximal Marginal Relevance):** Deduplicates near-identical results from similar daily logs.
- **Optional QMD backend:** A local search sidecar that adds reranking. Markdown stays the source of truth.

The key insight: **the files stay human-readable markdown.** The vector index is a search layer over them, not a replacement. You can still `grep` your memories or edit them by hand.

### Open-Source Memory Ecosystem (2026)

| Project | Approach | Standout Feature |
|---|---|---|
| **[Mem0](https://github.com/mem0ai/mem0)** | Universal memory layer for AI agents | 26% accuracy uplift over OpenAI's memory; 91% latency reduction; automatic decay and deduplication |
| **[MemGPT / Letta](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)** | OS-like virtual memory with paging | Agent autonomously decides what to keep in active context vs. archive — best for long-running agents |
| **[Memori](https://github.com/GibsonAI/Memori)** | Framework-agnostic memory with knowledge graphs | Stores semantic triples alongside vectors; plugs into any LLM/datastore |
| **[Cognee](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)** | Semantic memory engine | Turns conversations, docs, images, audio into memory nodes and edges |

Notable research papers (Jan–Feb 2026):
- **EverMemOS** — Self-organizing memory OS for structured long-horizon reasoning
- **MemRL** — Self-evolving agents via runtime reinforcement learning on episodic memory
- **Agentic Memory** — Unified long-term and short-term memory management for LLM agents
- **MemVerse** — Multimodal memory for lifelong learning agents

---

## What's the easiest way to integrate longer-term memory into Claude Code seamlessly?

### Integration Options

| Option | Effort | How It Works |
|---|---|---|
| **A. Curated MEMORY.md** | 20 minutes | Nightly script reads OG's daily logs + facts, deduplicates, prunes stale entries, writes clean summary into Claude Code's `MEMORY.md`. Batch, one-directional. |
| **B. MCP Server** | Moderate | Real-time bidirectional memory. Claude Code calls `memory_search`/`memory_save` natively as tools. OG's `Memory` class already has the right interface. |
| **C. Hook + Flat Files** | Light | Claude Code `post_message` hook appends summaries to daily logs. On session start, injects recent context into `MEMORY.md`. Temporal memory without an MCP server. |

**Recommended path:** Start with Option A (tonight), build toward Option B (MCP server) for real-time bidirectional memory.

### OG Memory Upgrade Path

The memory system is currently at Stage 1 (flat files + keyword search). The upgrade path is incremental — the `search(query) -> list[str]` interface stays the same:

| Stage | Implementation | What It Gets You |
|---|---|---|
| **1. Current** | Markdown files + `str.contains()` | Works for hundreds of facts |
| **2. BM25** | Add `rank_bm25` (pure Python, ~20 lines) | Proper term-frequency scoring, relevance ranking |
| **3. Hybrid search** | Add local vector embeddings via `sentence-transformers` or GGUF model; store in `sqlite-vec` or ChromaDB | Semantic similarity — "deploy" matches "push to production" |
| **4. Full memory system** | Add memory types (episodic, semantic, procedural), temporal decay, consolidation, deduplication | Mem0-level intelligence; agent improves over time |

---

## What is the potential, and how might we integrate into daily workflows?

### Potential Uses

**As a personal dev tool:**
- A `og` command that understands your project, reads your code, runs your tests, and commits your changes — all from natural language.
- Custom skills for specific workflows (deploy, review PR, run migrations, update deps).

**As an architecture template:**
- The patterns here map directly to production agent systems. The channel abstraction means adding a Slack bot or web API with ~50 lines of new code.
- The session/memory system is the foundation for agents that improve over time.

**As a domain-specific assistant:**
- An AI assistant that operates on domain files, runs analysis, and remembers context across sessions.
- Skills authored as markdown by domain experts, not engineers.

### Integration Timeline

**Immediate:**
- Add project-specific skills as markdown files.
- Run `og` from your project root and use it as a contextual assistant that knows your files.
- Use `--session` to maintain separate contexts per project.

**Short-term:**
- Add a project config that auto-loads when `og` runs in a directory.
- Hook into git pre-commit to auto-summarize changes.
- Add a `/cost` command to check budget without an API call.

**Medium-term:**
- Add a second channel (Slack or HTTP API) — the `Channel` ABC is already in place.
- Multi-agent: a router that dispatches to specialized agents (code agent, research agent, ops agent).
- RAG over a codebase via an `index` skill that builds embeddings.

---

## Bottom Line

The core takeaway: **the patterns are simple, composable, and cheap to run.** The agent loop + 4 tools + markdown skills + JSONL persistence is a surprisingly complete foundation. Everything else is just new skills and new channels.

---

## References

- [OpenClaw Memory Docs](https://docs.openclaw.ai/concepts/memory)
- [OpenClaw Memory Architecture Explained](https://shivamagarwal7.medium.com/agentic-ai-openclaw-moltbot-clawdbots-memory-architecture-explained-61c3b9697488)
- [Mem0 — Universal Memory Layer](https://github.com/mem0ai/mem0)
- [Memori — GibsonAI](https://github.com/GibsonAI/Memori)
- [Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)
- [6 Open-Source AI Memory Tools](https://medium.com/@jununhsu/6-open-source-ai-memory-tools-to-give-your-agents-long-term-memory-39992e6a3dc6)
- [Best AI Agent Memory Solutions 2026](https://fast.io/resources/best-ai-agent-memory-solutions/)
- [Mem0 Research — 26% Accuracy Boost](https://mem0.ai/research)
- [Building Memory-Driven AI Agents (MarkTechPost)](https://www.marktechpost.com/2026/02/01/how-to-build-memory-driven-ai-agents-with-short-term-long-term-and-episodic-memory/)

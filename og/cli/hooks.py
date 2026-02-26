"""Hook implementations for Claude Code integration: recall, extract, inject."""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from og.config.schema import Config

logger = logging.getLogger(__name__)

INJECT_SQL = """
SELECT chunk_type, text FROM context_chunks
WHERE project_id = $1 AND chunk_type IN ('decision', 'constraint', 'pattern', 'correction')
ORDER BY created_at DESC LIMIT $2;
"""

INJECT_ALL_SQL = """
SELECT chunk_type, text FROM context_chunks
WHERE chunk_type IN ('decision', 'constraint', 'pattern', 'correction')
ORDER BY created_at DESC LIMIT $1;
"""


async def create_pool(config: Config):
    """Create a lightweight asyncpg connection pool for hook subcommands."""
    import asyncpg

    return await asyncpg.create_pool(
        dsn=config.db.dsn,
        min_size=1,
        max_size=3,
    )


async def recall_impl(
    query: str,
    project_id: str,
    entities: list[str] | None = None,
    limit: int = 10,
) -> str:
    """Search memory for relevant context chunks. Falls back to flat-file Memory."""
    load_dotenv()
    config = Config()
    if project_id:
        config.memory.project_id = project_id

    # Try PG-backed search first
    try:
        pool = await create_pool(config)
        try:
            from og.memory.embeddings import EmbeddingClient
            from og.memory.pg import PgMemory

            embedder = EmbeddingClient(
                base_url=config.embedding.ollama_base_url,
                model=config.embedding.model,
            )

            graph = None
            if entities:
                from og.knowledge.graph import KnowledgeGraph

                graph = KnowledgeGraph(pool, config.memory.project_id)

            pg_mem = PgMemory(pool, embedder, config.memory.project_id, graph=graph)
            results = await pg_mem.search(query, limit=limit, entities=entities)
            if results:
                return "\n".join(f"- {text}" for text in results)
        finally:
            await pool.close()
    except Exception:
        logger.debug("PG recall failed, falling back to flat-file", exc_info=True)

    # Flat-file fallback
    from og.memory.manager import Memory

    mem = Memory(config.memory.storage_dir)
    results = await mem.search(query, limit=limit)
    if results:
        return "\n".join(results)

    return ""


async def extract_impl(
    transcript_path: str,
    session_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Parse a transcript and extract knowledge into PG. Returns summary."""
    load_dotenv()
    config = Config()
    proj = project_id or config.memory.project_id
    sid = session_id or "unknown"

    from og.cli.transcript import parse_transcript

    conversation_text = parse_transcript(transcript_path)
    if not conversation_text:
        return "No conversation content found."

    try:
        pool = await create_pool(config)
        try:
            from og.knowledge.extractor import KnowledgeExtractor
            from og.knowledge.graph import KnowledgeGraph
            from og.knowledge.hooks import PreCompactHook
            from og.memory.embeddings import EmbeddingClient

            embedder = EmbeddingClient(
                base_url=config.embedding.ollama_base_url,
                model=config.embedding.model,
            )
            extractor = KnowledgeExtractor()
            graph = KnowledgeGraph(pool, proj)

            hook = PreCompactHook(pool, embedder, extractor, graph, proj)
            count = await hook.run(sid, conversation_text)
            return f"Extracted {count} chunks."
        finally:
            await pool.close()
    except Exception:
        logger.warning("extract_impl failed", exc_info=True)
        return "Extraction failed (DB unavailable)."


async def inject_impl(
    project_id: str | None = None,
    limit: int = 20,
) -> str:
    """Fetch high-value context chunks and format for injection into Claude context."""
    load_dotenv()
    config = Config()
    proj = project_id

    # Try PG-backed injection
    try:
        pool = await create_pool(config)
        try:
            if proj:
                rows = await pool.fetch(INJECT_SQL, proj, limit)
            else:
                rows = await pool.fetch(INJECT_ALL_SQL, limit)
            if rows:
                return _format_inject_rows(rows)
        finally:
            await pool.close()
    except Exception:
        logger.debug("PG inject failed, falling back to flat-file", exc_info=True)

    # Flat-file fallback: read MEMORY.md
    memory_path = Path(config.memory.storage_dir).expanduser() / config.memory.memory_file
    if memory_path.exists():
        content = memory_path.read_text(encoding="utf-8").strip()
        if content:
            return f"# \U0001f7e2 OG Active — Recalled Context\n\n{content}"

    return ""


def _format_inject_rows(rows) -> str:
    """Group chunks by type and format as markdown sections."""
    groups: dict[str, list[str]] = {}
    for row in rows:
        chunk_type = row["chunk_type"]
        groups.setdefault(chunk_type, []).append(row["text"])

    type_labels = {
        "decision": "Decisions",
        "constraint": "Constraints",
        "pattern": "Patterns",
        "correction": "Corrections",
    }

    sections = []
    for ctype in ("decision", "constraint", "pattern", "correction"):
        items = groups.get(ctype, [])
        if items:
            label = type_labels.get(ctype, ctype.capitalize())
            bullets = "\n".join(f"- {text}" for text in items)
            sections.append(f"## {label}\n\n{bullets}")

    if not sections:
        return ""

    return "# \U0001f7e2 OG Active — Recalled Context\n\n" + "\n\n".join(sections)

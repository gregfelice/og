"""PostgreSQL-backed memory with hybrid search (pgvector cosine + tsvector BM25, RRF fusion)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from og.memory.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

HYBRID_SEARCH_SQL = """
WITH semantic AS (
    SELECT id, text, ROW_NUMBER() OVER (ORDER BY embedding <=> $1::vector) AS rank_s
    FROM context_chunks WHERE project_id = $3 AND embedding IS NOT NULL
    ORDER BY embedding <=> $1::vector LIMIT 30
),
keyword AS (
    SELECT id, text, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(text_search, q) DESC) AS rank_k
    FROM context_chunks, websearch_to_tsquery('english', $2) q
    WHERE text_search @@ q AND project_id = $3 LIMIT 30
),
fused AS (
    SELECT COALESCE(s.id, k.id) AS id, COALESCE(s.text, k.text) AS text,
           COALESCE(1.0/(s.rank_s+60),0) + COALESCE(1.0/(k.rank_k+60),0) AS rrf
    FROM semantic s FULL OUTER JOIN keyword k USING (id)
)
SELECT text FROM fused ORDER BY rrf DESC LIMIT $4;
"""

INSERT_CHUNK_SQL = """
INSERT INTO context_chunks (project_id, chunk_type, text, embedding, source_type)
VALUES ($1, $2, $3, $4::vector, $5)
ON CONFLICT ON CONSTRAINT uq_chunk_text DO NOTHING;
"""


class PgMemory:
    """PostgreSQL + pgvector memory store with hybrid semantic/keyword search."""

    def __init__(self, pool: asyncpg.Pool, embedder: EmbeddingClient, project_id: str):
        self.pool = pool
        self.embedder = embedder
        self.project_id = project_id

    async def search(self, query: str, limit: int = 10) -> list[str]:
        """Hybrid search: pgvector cosine (top 30) + tsvector BM25 (top 30), fused via RRF."""
        try:
            embedding = await self.embedder.embed(query)
            rows = await self.pool.fetch(
                HYBRID_SEARCH_SQL, embedding, query, self.project_id, limit
            )
            return [row["text"] for row in rows]
        except Exception:
            logger.warning("PgMemory.search failed, returning empty", exc_info=True)
            return []

    async def log(self, user_msg: str, assistant_msg: str) -> None:
        """Embed and store a conversation exchange."""
        try:
            text = f"User: {user_msg[:200]}\nAssistant: {assistant_msg[:500]}"
            embedding = await self.embedder.embed(text)
            await self.pool.execute(
                INSERT_CHUNK_SQL,
                self.project_id,
                "conversation",
                text,
                embedding,
                "agent_extract",
            )
        except Exception:
            logger.warning("PgMemory.log failed", exc_info=True)

    async def save_fact(self, fact: str) -> None:
        """Embed and store a fact."""
        try:
            embedding = await self.embedder.embed(fact)
            await self.pool.execute(
                INSERT_CHUNK_SQL,
                self.project_id,
                "fact",
                fact,
                embedding,
                "manual",
            )
        except Exception:
            logger.warning("PgMemory.save_fact failed", exc_info=True)

    async def load_memory(self, message: str = "", limit: int = 10) -> str:
        """Search memory for relevant context and format as bullet list."""
        if not message:
            return ""
        try:
            results = await self.search(message, limit=limit)
            if not results:
                return ""
            lines = [f"- {text}" for text in results]
            return "\n".join(lines)
        except Exception:
            logger.warning("PgMemory.load_memory failed", exc_info=True)
            return ""

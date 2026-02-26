"""Pre-compact hook: extract knowledge from conversations before compaction."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

    from og.knowledge.extractor import KnowledgeExtractor
    from og.knowledge.graph import KnowledgeGraph
    from og.memory.embeddings import EmbeddingClient

logger = logging.getLogger(__name__)

INSERT_CHUNK_SQL = """
INSERT INTO context_chunks (project_id, chunk_type, text, embedding, source_session, source_type)
VALUES ($1, $2, $3, $4::vector, $5, 'pre_compact')
ON CONFLICT (project_id, md5(text))
DO UPDATE SET last_accessed = now(), access_count = context_chunks.access_count + 1
RETURNING id;
"""


class PreCompactHook:
    """Orchestrates knowledge extraction → embedding → storage → graph linking."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedder: EmbeddingClient,
        extractor: KnowledgeExtractor,
        graph: KnowledgeGraph,
        project_id: str,
    ):
        self.pool = pool
        self.embedder = embedder
        self.extractor = extractor
        self.graph = graph
        self.project_id = project_id

    async def run(self, session_id: str, conversation_text: str) -> int:
        """Extract knowledge from a conversation and store it.

        Returns the number of chunks stored.
        """
        # 1. Extract knowledge chunks via LLM
        chunks = await self.extractor.extract(conversation_text)
        if not chunks:
            return 0

        # 2. Batch embed all chunk texts
        texts = [c.text for c in chunks]
        try:
            embeddings = await self.embedder.embed_batch(texts)
        except Exception:
            logger.warning("Batch embedding failed for knowledge chunks", exc_info=True)
            return 0

        # 3. Store chunks + create graph vertices in a transaction
        stored_count = 0
        chunk_db_ids: list[int | None] = []
        vertex_ids: list[int | None] = []

        try:
            async with self.pool.acquire() as conn:
                await conn.execute("LOAD 'age';")
                await conn.execute("SET search_path = ag_catalog, public;")

                async with conn.transaction():
                    # Ensure session vertex exists
                    from og.knowledge.graph import _escape, _cypher_query

                    safe_id = _escape(session_id)
                    safe_proj = _escape(self.project_id)
                    cypher = (
                        f"MERGE (s:Session {{session_id: '{safe_id}', "
                        f"project_id: '{safe_proj}'}}) RETURN id(s)"
                    )
                    sql = _cypher_query(cypher, "vid agtype")
                    rows = await conn.fetch(sql)
                    from og.knowledge.graph import _parse_agtype_id

                    session_vid = _parse_agtype_id(rows[0]["vid"]) if rows else None

                    for i, chunk in enumerate(chunks):
                        # Insert into context_chunks
                        row = await conn.fetchrow(
                            INSERT_CHUNK_SQL,
                            self.project_id,
                            chunk.chunk_type,
                            chunk.text,
                            embeddings[i],
                            session_id,
                        )
                        chunk_id = row["id"] if row else None
                        chunk_db_ids.append(chunk_id)

                        if chunk_id is not None:
                            stored_count += 1

                            # Create graph vertex
                            vid = await self.graph.create_vertex_in_tx(
                                conn, chunk_id, chunk.chunk_type, chunk.text, chunk.entities
                            )
                            vertex_ids.append(vid)

                            # Link to session
                            if vid is not None and session_vid is not None:
                                await self.graph.link_to_session_in_tx(conn, vid, session_vid)
                        else:
                            vertex_ids.append(None)

                    # 4. Create inter-chunk edges
                    for i, chunk in enumerate(chunks):
                        if vertex_ids[i] is None or not chunk.relation_type:
                            continue
                        for related_idx in chunk.related_to:
                            if (
                                0 <= related_idx < len(vertex_ids)
                                and vertex_ids[related_idx] is not None
                            ):
                                await self.graph.create_edge_in_tx(
                                    conn,
                                    vertex_ids[i],
                                    vertex_ids[related_idx],
                                    chunk.relation_type,
                                )

        except Exception:
            logger.warning("PreCompactHook transaction failed", exc_info=True)

        return stored_count

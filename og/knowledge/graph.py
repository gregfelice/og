"""Apache AGE knowledge graph operations."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

GRAPH_NAME = "og_knowledge"
AGE_SEARCH_PATH = "SET search_path = ag_catalog, public;"


def _escape(s: str) -> str:
    """Escape a string for use in a Cypher literal."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


def _parse_agtype_id(val: Any) -> int | None:
    """Parse an agtype value to extract a vertex/edge id."""
    if val is None:
        return None
    s = str(val)
    # agtype ids look like "12345::bigint" or just an integer
    match = re.search(r"(\d+)", s)
    return int(match.group(1)) if match else None


def _parse_agtype_float(val: Any) -> float:
    """Parse an agtype value to a float."""
    if val is None:
        return 0.0
    s = str(val).rstrip("::float8").rstrip("::numeric")
    try:
        return float(re.search(r"[\d.]+", s).group(0))
    except (AttributeError, ValueError):
        return 0.0


def _cypher_query(cypher: str, result_columns: str) -> str:
    """Build the SQL wrapper for a Cypher query."""
    return f"SELECT * FROM cypher('{GRAPH_NAME}', $$ {cypher} $$) AS ({result_columns});"


class KnowledgeGraph:
    """Apache AGE graph operations for knowledge storage and retrieval."""

    def __init__(self, pool: asyncpg.Pool, project_id: str):
        self.pool = pool
        self.project_id = project_id

    async def _execute_cypher(self, cypher: str, result_columns: str) -> list[asyncpg.Record]:
        """Execute a Cypher query and return results."""
        sql = _cypher_query(cypher, result_columns)
        try:
            async with self.pool.acquire() as conn:
                try:
                    await conn.execute("LOAD 'age';")
                except Exception:
                    pass  # Already loaded via shared_preload_libraries
                await conn.execute(AGE_SEARCH_PATH)
                return await conn.fetch(sql)
        except Exception:
            logger.warning("Cypher query failed: %s", cypher[:100], exc_info=True)
            return []

    async def _execute_cypher_in_tx(
        self, conn: asyncpg.Connection, cypher: str, result_columns: str
    ) -> list[asyncpg.Record]:
        """Execute a Cypher query within an existing connection/transaction."""
        sql = _cypher_query(cypher, result_columns)
        try:
            return await conn.fetch(sql)
        except Exception:
            logger.warning("Cypher query failed in tx: %s", cypher[:100], exc_info=True)
            return []

    async def ensure_session_vertex(self, session_id: str) -> int | None:
        """Create or find a Session vertex, return its id."""
        safe_id = _escape(session_id)
        safe_proj = _escape(self.project_id)
        cypher = (
            f"MERGE (s:Session {{session_id: '{safe_id}', project_id: '{safe_proj}'}}) RETURN id(s)"
        )
        rows = await self._execute_cypher(cypher, "vid agtype")
        if rows:
            return _parse_agtype_id(rows[0]["vid"])
        return None

    async def create_vertex(
        self,
        chunk_id: int,
        chunk_type: str,
        text: str,
        entities: list[str],
    ) -> int | None:
        """Create a knowledge vertex and return its graph id."""
        label = chunk_type.capitalize()
        # Validate label exists in our schema
        valid_labels = {"Decision", "Correction", "Constraint", "Pattern", "Fact"}
        if label not in valid_labels:
            label = "Pattern"

        safe_text = _escape(text[:500])
        entity_str = ", ".join(f"'{_escape(e)}'" for e in entities[:10])

        cypher = (
            f"CREATE (n:{label} {{chunk_id: {chunk_id}, text: '{safe_text}', "
            f"entities: [{entity_str}], project_id: '{_escape(self.project_id)}'}}) "
            f"RETURN id(n)"
        )
        rows = await self._execute_cypher(cypher, "vid agtype")
        if rows:
            return _parse_agtype_id(rows[0]["vid"])
        return None

    async def create_vertex_in_tx(
        self,
        conn: asyncpg.Connection,
        chunk_id: int,
        chunk_type: str,
        text: str,
        entities: list[str],
    ) -> int | None:
        """Create a vertex within an existing transaction."""
        label = chunk_type.capitalize()
        valid_labels = {"Decision", "Correction", "Constraint", "Pattern", "Fact"}
        if label not in valid_labels:
            label = "Pattern"

        safe_text = _escape(text[:500])
        entity_str = ", ".join(f"'{_escape(e)}'" for e in entities[:10])

        cypher = (
            f"CREATE (n:{label} {{chunk_id: {chunk_id}, text: '{safe_text}', "
            f"entities: [{entity_str}], project_id: '{_escape(self.project_id)}'}}) "
            f"RETURN id(n)"
        )
        rows = await self._execute_cypher_in_tx(conn, cypher, "vid agtype")
        if rows:
            return _parse_agtype_id(rows[0]["vid"])
        return None

    async def create_edge(self, from_vertex_id: int, to_vertex_id: int, edge_type: str) -> None:
        """Create an edge between two vertices."""
        valid_edges = {
            "CONTRADICTS",
            "SUPERSEDES",
            "DEPENDS_ON",
            "REJECTED_IN_FAVOR_OF",
            "DISCOVERED_IN",
            "CAUSED_BY",
        }
        if edge_type not in valid_edges:
            return

        cypher = (
            f"MATCH (a), (b) WHERE id(a) = {from_vertex_id} AND id(b) = {to_vertex_id} "
            f"CREATE (a)-[:{edge_type}]->(b)"
        )
        await self._execute_cypher(cypher, "dummy agtype")

    async def create_edge_in_tx(
        self, conn: asyncpg.Connection, from_vertex_id: int, to_vertex_id: int, edge_type: str
    ) -> None:
        """Create an edge within an existing transaction."""
        valid_edges = {
            "CONTRADICTS",
            "SUPERSEDES",
            "DEPENDS_ON",
            "REJECTED_IN_FAVOR_OF",
            "DISCOVERED_IN",
            "CAUSED_BY",
        }
        if edge_type not in valid_edges:
            return

        cypher = (
            f"MATCH (a), (b) WHERE id(a) = {from_vertex_id} AND id(b) = {to_vertex_id} "
            f"CREATE (a)-[:{edge_type}]->(b)"
        )
        await self._execute_cypher_in_tx(conn, cypher, "dummy agtype")

    async def link_to_session(self, chunk_vertex_id: int, session_id: str) -> None:
        """Link a knowledge vertex to its source session."""
        session_vid = await self.ensure_session_vertex(session_id)
        if session_vid is None:
            return
        cypher = (
            f"MATCH (c), (s) WHERE id(c) = {chunk_vertex_id} AND id(s) = {session_vid} "
            f"CREATE (c)-[:DISCOVERED_IN]->(s)"
        )
        await self._execute_cypher(cypher, "dummy agtype")

    async def link_to_session_in_tx(
        self, conn: asyncpg.Connection, chunk_vertex_id: int, session_vid: int
    ) -> None:
        """Link a vertex to session within a transaction."""
        cypher = (
            f"MATCH (c), (s) WHERE id(c) = {chunk_vertex_id} AND id(s) = {session_vid} "
            f"CREATE (c)-[:DISCOVERED_IN]->(s)"
        )
        await self._execute_cypher_in_tx(conn, cypher, "dummy agtype")

    async def find_contradictions(self, entities: list[str]) -> list[dict[str, Any]]:
        """Find CONTRADICTS edges involving the given entities."""
        if not entities:
            return []

        # Match vertices that share entities with the query, then traverse CONTRADICTS edges
        entity_conditions = " OR ".join(f"'{_escape(e)}' IN n.entities" for e in entities[:5])
        cypher = (
            f"MATCH (n)-[:CONTRADICTS]-(m) "
            f"WHERE ({entity_conditions}) AND n.project_id = '{_escape(self.project_id)}' "
            f"RETURN n.text, m.text, n.chunk_id, m.chunk_id LIMIT 10"
        )
        rows = await self._execute_cypher(
            cypher, "text1 agtype, text2 agtype, id1 agtype, id2 agtype"
        )

        results = []
        for row in rows:
            results.append(
                {
                    "statement_a": str(row["text1"]).strip('"'),
                    "statement_b": str(row["text2"]).strip('"'),
                    "chunk_id_a": _parse_agtype_id(row["id1"]),
                    "chunk_id_b": _parse_agtype_id(row["id2"]),
                }
            )
        return results

    async def retrieve_related(self, entities: list[str], limit: int = 30) -> list[dict[str, Any]]:
        """Multi-hop traversal: find chunks related to the given entities."""
        if not entities:
            return []

        entity_conditions = " OR ".join(f"'{_escape(e)}' IN n.entities" for e in entities[:5])
        # 1-2 hop traversal for related knowledge
        cypher = (
            f"MATCH (n)-[*1..2]-(m) "
            f"WHERE ({entity_conditions}) AND n.project_id = '{_escape(self.project_id)}' "
            f"AND m.chunk_id IS NOT NULL "
            f"WITH DISTINCT m.chunk_id AS chunk_id, "
            f"count(*) AS path_count "
            f"RETURN chunk_id, path_count "
            f"ORDER BY path_count DESC LIMIT {limit}"
        )
        rows = await self._execute_cypher(cypher, "chunk_id agtype, path_count agtype")

        results = []
        for row in rows:
            cid = _parse_agtype_id(row["chunk_id"])
            score = _parse_agtype_float(row["path_count"])
            if cid is not None:
                results.append({"chunk_id": cid, "path_score": score})
        return results

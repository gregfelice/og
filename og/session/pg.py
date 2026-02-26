"""PostgreSQL-backed session event store."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from og.session.store import replay_events_to_messages

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

INSERT_EVENT_SQL = """
INSERT INTO session_events (session_id, project_id, event_type, content, token_count, created_at)
VALUES ($1, $2, $3, $4::jsonb, $5, to_timestamp($6))
"""

LOAD_SQL = """
SELECT event_type, content, created_at
FROM session_events
WHERE session_id = $1 AND project_id = $2
ORDER BY created_at ASC, id ASC
"""

LOAD_LAZY_SQL = """
SELECT event_type, content, created_at FROM (
    SELECT event_type, content, created_at
    FROM session_events
    WHERE session_id = $1 AND project_id = $2
    ORDER BY created_at DESC, id DESC
    LIMIT $3
) sub ORDER BY created_at ASC
"""

EXISTS_SQL = """
SELECT 1 FROM session_events
WHERE session_id = $1 AND project_id = $2
LIMIT 1
"""

SEARCH_SQL = """
SELECT DISTINCT session_id, MIN(created_at) AS first_event
FROM session_events
WHERE project_id = $1 AND content::text ILIKE '%' || $2 || '%'
GROUP BY session_id
ORDER BY first_event DESC
LIMIT $3
"""

LIST_SQL = """
SELECT session_id, MIN(created_at) AS started, MAX(created_at) AS last_active,
       COUNT(*) AS event_count
FROM session_events
WHERE project_id = $1
GROUP BY session_id
ORDER BY last_active DESC
"""


class PgSessionStore:
    """PostgreSQL-backed session store with lazy loading and cross-session search."""

    def __init__(self, pool: asyncpg.Pool, project_id: str):
        self.pool = pool
        self.project_id = project_id

    async def append(self, session_id: str, event: dict[str, Any]) -> None:
        """Insert a session event into PostgreSQL."""
        timestamp = event.get("timestamp", time.time())
        event_type = event.get("type", "unknown")
        # Store everything except 'type' and 'timestamp' in the JSONB content column
        content = {k: v for k, v in event.items() if k not in ("type", "timestamp")}
        token_count = content.pop("token_count", None)

        try:
            await self.pool.execute(
                INSERT_EVENT_SQL,
                session_id,
                self.project_id,
                event_type,
                json.dumps(content, default=str),
                token_count,
                timestamp,
            )
        except Exception:
            logger.warning("PgSessionStore.append failed", exc_info=True)

    async def load(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Load session events. Use limit for lazy loading (last N events)."""
        try:
            if limit is not None:
                rows = await self.pool.fetch(LOAD_LAZY_SQL, session_id, self.project_id, limit)
            else:
                rows = await self.pool.fetch(LOAD_SQL, session_id, self.project_id)

            events = []
            for row in rows:
                content = (
                    json.loads(row["content"])
                    if isinstance(row["content"], str)
                    else row["content"]
                )
                event = {"type": row["event_type"], **content}
                events.append(event)
            return events
        except Exception:
            logger.warning("PgSessionStore.load failed", exc_info=True)
            return []

    async def exists(self, session_id: str) -> bool:
        """Check if a session has any events."""
        try:
            row = await self.pool.fetchrow(EXISTS_SQL, session_id, self.project_id)
            return row is not None
        except Exception:
            logger.warning("PgSessionStore.exists failed", exc_info=True)
            return False

    async def search_sessions(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search across sessions for events containing keyword."""
        try:
            rows = await self.pool.fetch(SEARCH_SQL, self.project_id, keyword, limit)
            return [
                {"session_id": row["session_id"], "first_event": row["first_event"]} for row in rows
            ]
        except Exception:
            logger.warning("PgSessionStore.search_sessions failed", exc_info=True)
            return []

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions with metadata."""
        try:
            rows = await self.pool.fetch(LIST_SQL, self.project_id)
            return [
                {
                    "session_id": row["session_id"],
                    "started": row["started"],
                    "last_active": row["last_active"],
                    "event_count": row["event_count"],
                }
                for row in rows
            ]
        except Exception:
            logger.warning("PgSessionStore.list_sessions failed", exc_info=True)
            return []

    def to_messages(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replay events into Anthropic message format."""
        return replay_events_to_messages(events)

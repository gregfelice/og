"""PostgreSQL-backed budget tracker."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from og.core.budget import PRICING, DEFAULT_PRICING, BudgetExceeded

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

SUM_SQL = "SELECT COALESCE(SUM(cost_usd), 0)::float FROM budget_ledger WHERE project_id = $1"

INSERT_SQL = """
INSERT INTO budget_ledger (project_id, session_id, model, input_tokens, output_tokens, cost_usd)
VALUES ($1, $2, $3, $4, $5, $6)
"""


class PgBudgetTracker:
    """PostgreSQL-backed budget tracker with lazy total loading."""

    def __init__(self, pool: asyncpg.Pool, project_id: str, budget_limit: float):
        self.pool = pool
        self.project_id = project_id
        self.budget_limit = budget_limit
        self._total_cost: float | None = None  # Lazy-loaded

    async def _ensure_total(self) -> None:
        """Lazy-load the running total from the database on first access."""
        if self._total_cost is not None:
            return
        try:
            row = await self.pool.fetchrow(SUM_SQL, self.project_id)
            self._total_cost = row[0] if row else 0.0
        except Exception:
            logger.warning("PgBudgetTracker: failed to load total, assuming 0", exc_info=True)
            self._total_cost = 0.0

    async def check(self) -> None:
        """Raise BudgetExceeded if we've hit the limit."""
        await self._ensure_total()
        if self._total_cost >= self.budget_limit:
            raise BudgetExceeded(
                f"Budget exhausted: ${self._total_cost:.4f} / ${self.budget_limit:.2f}"
            )

    async def record(
        self, model: str, input_tokens: int, output_tokens: int, session_id: str = ""
    ) -> float:
        """Record token usage to PostgreSQL and return the cost."""
        pricing = PRICING.get(model, DEFAULT_PRICING)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

        await self._ensure_total()
        self._total_cost += cost

        try:
            await self.pool.execute(
                INSERT_SQL,
                self.project_id,
                session_id,
                model,
                input_tokens,
                output_tokens,
                cost,
            )
        except Exception:
            logger.warning("PgBudgetTracker.record failed", exc_info=True)

        return cost

    @property
    def total_cost(self) -> float:
        return self._total_cost if self._total_cost is not None else 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget_limit - self.total_cost)

    def summary(self) -> str:
        return (
            f"${self.total_cost:.4f} / ${self.budget_limit:.2f} (${self.remaining:.4f} remaining)"
        )

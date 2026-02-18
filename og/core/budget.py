"""Token usage tracking and budget enforcement."""

from __future__ import annotations

import json
from pathlib import Path

# Pricing per million tokens (USD) as of 2025
# https://docs.anthropic.com/en/docs/about-claude/models
PRICING: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
}

# Fallback for unknown models — use Sonnet pricing as a safe estimate
DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


class BudgetExceeded(Exception):
    """Raised when spending would exceed the configured budget."""


class BudgetTracker:
    """Tracks API costs and enforces a spending cap."""

    def __init__(self, budget_limit: float, ledger_path: Path):
        self.budget_limit = budget_limit
        self.ledger_path = ledger_path
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._total_cost = self._load_total()

    def _load_total(self) -> float:
        if not self.ledger_path.exists():
            return 0.0
        total = 0.0
        with open(self.ledger_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    total += entry.get("cost", 0.0)
        return total

    def check(self) -> None:
        """Raise BudgetExceeded if we've hit the limit."""
        if self._total_cost >= self.budget_limit:
            raise BudgetExceeded(
                f"Budget exhausted: ${self._total_cost:.4f} / ${self.budget_limit:.2f}"
            )

    def record(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Record token usage and return the cost of this call."""
        pricing = PRICING.get(model, DEFAULT_PRICING)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        self._total_cost += cost

        entry = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost": cost,
            "total": self._total_cost,
        }
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return cost

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget_limit - self._total_cost)

    def summary(self) -> str:
        return f"${self._total_cost:.4f} / ${self.budget_limit:.2f} (${self.remaining:.4f} remaining)"

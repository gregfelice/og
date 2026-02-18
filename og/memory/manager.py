"""File-based memory: MEMORY.md + daily logs + keyword search."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class Memory:
    """Manages persistent memory via MEMORY.md and daily log files."""

    def __init__(self, storage_dir: Path, memory_file: str = "MEMORY.md", daily_dir: str = "daily"):
        self.storage_dir = Path(storage_dir).expanduser()
        self.memory_path = self.storage_dir / memory_file
        self.daily_dir = self.storage_dir / daily_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.daily_dir.mkdir(parents=True, exist_ok=True)

    def search(self, query: str, limit: int = 5) -> list[str]:
        """Keyword search across MEMORY.md and recent daily logs."""
        results = []
        query_lower = query.lower()
        keywords = query_lower.split()

        # Search MEMORY.md
        if self.memory_path.exists():
            for line in self.memory_path.read_text(encoding="utf-8").splitlines():
                if any(kw in line.lower() for kw in keywords):
                    results.append(f"[memory] {line.strip()}")

        # Search recent daily logs (last 7 days of files)
        log_files = sorted(self.daily_dir.glob("*.md"), reverse=True)[:7]
        for log_file in log_files:
            for line in log_file.read_text(encoding="utf-8").splitlines():
                if any(kw in line.lower() for kw in keywords):
                    results.append(f"[{log_file.stem}] {line.strip()}")

        return results[:limit]

    def log(self, user_msg: str, assistant_msg: str) -> None:
        """Append a conversation exchange to today's daily log."""
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = self.daily_dir / f"{today}.md"
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"\n## {timestamp}\n\n**User:** {user_msg[:200]}\n\n**Assistant:** {assistant_msg[:500]}\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def save_fact(self, fact: str) -> None:
        """Append a fact to MEMORY.md."""
        with open(self.memory_path, "a", encoding="utf-8") as f:
            f.write(f"- {fact}\n")

    def load_memory(self) -> str:
        """Load the full MEMORY.md contents."""
        if self.memory_path.exists():
            return self.memory_path.read_text(encoding="utf-8")
        return ""

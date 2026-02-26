"""Claude Code transcript parser — reads JSONL session transcripts."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_transcript(path: str | Path, max_chars: int = 16000) -> str:
    """Parse a Claude Code JSONL transcript into plain conversation text.

    Handles both string and list content formats:
        {"type":"user","message":{"role":"user","content":"hello"}}
        {"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"hi"}]}}

    Returns truncated text suitable for KnowledgeExtractor.
    """
    path = Path(path)
    if not path.exists():
        logger.warning("Transcript not found: %s", path)
        return ""

    lines: list[str] = []
    total_chars = 0

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        msg = entry.get("message")
        if not msg:
            continue

        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue

        content = msg.get("content", "")
        text = _extract_text(content)
        if not text:
            continue

        prefix = "User" if role == "user" else "Assistant"
        line = f"{prefix}: {text}"
        lines.append(line)
        total_chars += len(line)

        if total_chars >= max_chars:
            break

    result = "\n\n".join(lines)
    return result[:max_chars]


def _extract_text(content: str | list) -> str:
    """Extract plain text from Claude message content (string or content blocks)."""
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts).strip()

    return ""

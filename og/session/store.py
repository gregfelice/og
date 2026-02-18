"""JSONL append-only session event log."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SessionStore:
    """Manages JSONL session files for conversation persistence."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir).expanduser()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.storage_dir / f"{session_id}.jsonl"

    def append(self, session_id: str, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", time.time())
        with open(self._path(session_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def load(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        events = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def to_messages(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Replay events into Anthropic message format."""
        messages = []
        for event in events:
            etype = event.get("type")
            if etype == "user_message":
                messages.append({"role": "user", "content": event["content"]})
            elif etype == "assistant_message":
                messages.append({"role": "assistant", "content": event["content"]})
            elif etype == "tool_use":
                # Tool use blocks are part of the assistant message
                # They get bundled with the preceding assistant content
                if messages and messages[-1]["role"] == "assistant":
                    content = messages[-1]["content"]
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}] if content else []
                        messages[-1]["content"] = content
                    content.append({
                        "type": "tool_use",
                        "id": event["tool_use_id"],
                        "name": event["name"],
                        "input": event["input"],
                    })
                else:
                    messages.append({
                        "role": "assistant",
                        "content": [{
                            "type": "tool_use",
                            "id": event["tool_use_id"],
                            "name": event["name"],
                            "input": event["input"],
                        }],
                    })
            elif etype == "tool_result":
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": event["tool_use_id"],
                        "content": event["content"],
                        "is_error": event.get("is_error", False),
                    }],
                })
        return messages

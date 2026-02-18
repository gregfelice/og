"""Pi agent's 4 core tools: read, write, edit, bash."""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolResult:
    output: str
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.error is None


class ToolRegistry:
    """Registry of the 4 Pi agent tools."""

    def __init__(self, bash_timeout: int = 30):
        self.bash_timeout = bash_timeout

    async def execute(self, name: str, args: dict) -> ToolResult:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolResult(output="", error=f"Unknown tool: {name}")
        try:
            return await handler(**args)
        except Exception as e:
            return ToolResult(output="", error=str(e))

    async def _tool_read(self, path: str) -> ToolResult:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        if not p.is_file():
            return ToolResult(output="", error=f"Not a file: {path}")
        try:
            content = p.read_text(encoding="utf-8")
            return ToolResult(output=content)
        except UnicodeDecodeError:
            return ToolResult(output="", error=f"Cannot read binary file: {path}")

    async def _tool_write(self, path: str, content: str) -> ToolResult:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return ToolResult(output=f"Wrote {len(content)} bytes to {path}")

    async def _tool_edit(self, path: str, old_text: str, new_text: str) -> ToolResult:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return ToolResult(output="", error=f"File not found: {path}")
        content = p.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            return ToolResult(output="", error="old_text not found in file")
        if count > 1:
            return ToolResult(
                output="",
                error=f"old_text matches {count} locations — must be unique",
            )
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return ToolResult(output=f"Edited {path}")

    async def _tool_bash(self, command: str, timeout: int | None = None) -> ToolResult:
        timeout = timeout or self.bash_timeout
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace")
            err_output = stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                combined = output + err_output if output else err_output
                return ToolResult(
                    output=combined,
                    error=f"Exit code {proc.returncode}",
                )
            if err_output:
                output += err_output
            return ToolResult(output=output)
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(output="", error=f"Command timed out after {timeout}s")

    @staticmethod
    def get_tool_schemas() -> list[dict]:
        return [
            {
                "name": "read",
                "description": "Read the contents of a file at the given path.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to read.",
                        }
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write",
                "description": "Write content to a file, creating it if needed or overwriting.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to write to.",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full file content to write.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit",
                "description": "Search-and-replace edit on a file. old_text must match exactly once.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Path to the file to edit.",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Exact text to find (must be unique in the file).",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text.",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "bash",
                "description": "Execute a shell command with optional timeout.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute.",
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 30).",
                        },
                    },
                    "required": ["command"],
                },
            },
        ]

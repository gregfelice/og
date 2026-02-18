"""Rich-based terminal channel adapter."""

from __future__ import annotations

import asyncio
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from og.channels.base import Channel


class CLIChannel(Channel):
    """Terminal UI channel using Rich for formatted output."""

    def __init__(self):
        self.console = Console()
        self._stream_buffer: list[str] = []

    async def receive(self) -> str | None:
        self.console.print()
        try:
            # Run input in a thread to not block the event loop
            message = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.console.input("[bold cyan]you>[/bold cyan] "),
            )
        except (EOFError, KeyboardInterrupt):
            return None
        message = message.strip()
        if message.lower() in ("exit", "quit", "/quit", "/exit"):
            return None
        return message if message else ""

    async def send(self, message: str) -> None:
        self.console.print()
        md = Markdown(message)
        self.console.print(Panel(md, title="og", title_align="left", border_style="green"))

    async def stream(self, chunk: str) -> None:
        self._stream_buffer.append(chunk)
        # Print raw chunks for real-time feel
        sys.stdout.write(chunk)
        sys.stdout.flush()

    async def stream_end(self) -> None:
        self._stream_buffer.clear()
        sys.stdout.write("\n")
        sys.stdout.flush()

    async def show_status(self, status: str) -> None:
        self.console.print(f"  [dim]{status}[/dim]", end="\r")

    def print_welcome(self, session_id: str) -> None:
        self.console.print(
            Panel(
                "[bold]OG[/bold] — OpenClaw Python PoC\n"
                f"Session: [cyan]{session_id}[/cyan]\n"
                "Type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit.",
                border_style="blue",
            )
        )

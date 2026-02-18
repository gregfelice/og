"""Abstract channel interface for message I/O."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Channel(ABC):
    """Base class for message channels (CLI, Slack, etc.)."""

    @abstractmethod
    async def receive(self) -> str | None:
        """Receive a message from the user. Returns None on EOF/exit."""

    @abstractmethod
    async def send(self, message: str) -> None:
        """Send a complete message to the user."""

    @abstractmethod
    async def stream(self, chunk: str) -> None:
        """Stream a partial message chunk to the user."""

    @abstractmethod
    async def stream_end(self) -> None:
        """Signal end of a streamed message."""

    @abstractmethod
    async def show_status(self, status: str) -> None:
        """Show a status indicator (e.g., 'Thinking...')."""

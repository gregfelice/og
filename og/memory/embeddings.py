"""Embedding client using OpenAI SDK pointed at local Ollama."""

from __future__ import annotations

from openai import AsyncOpenAI


class EmbeddingClient:
    """Async embedding client wrapping Ollama's OpenAI-compatible endpoint."""

    def __init__(self, base_url: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(base_url=base_url, api_key="ollama")

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        resp = await self._client.embeddings.create(model=self.model, input=text)
        return resp.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings."""
        resp = await self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in resp.data]

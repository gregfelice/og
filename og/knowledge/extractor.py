"""LLM-powered knowledge extraction from conversations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Analyze this conversation and extract structured knowledge chunks.

For each piece of knowledge, return a JSON object with:
- chunk_type: one of "decision", "correction", "constraint", "pattern", "fact"
- text: A declarative statement (1-3 sentences) capturing the knowledge
- entities: List of code entities, concepts, or technologies mentioned
- related_to: List of indices (0-based) of other chunks this one relates to
- relation_type: One of "CONTRADICTS", "SUPERSEDES", "DEPENDS_ON", "REJECTED_IN_FAVOR_OF", or null

Focus on:
- Architectural decisions made
- Corrections or changes in approach
- Constraints discovered (technical limits, requirements)
- Patterns established (coding conventions, workflows)
- Important facts learned

Return ONLY a JSON array of these objects. If no knowledge worth extracting, return [].

Conversation:
{conversation}"""


@dataclass
class KnowledgeChunk:
    chunk_type: str
    text: str
    entities: list[str] = field(default_factory=list)
    related_to: list[int] = field(default_factory=list)
    relation_type: str | None = None


VALID_CHUNK_TYPES = {"decision", "correction", "constraint", "pattern", "fact"}
VALID_RELATIONS = {"CONTRADICTS", "SUPERSEDES", "DEPENDS_ON", "REJECTED_IN_FAVOR_OF"}


class KnowledgeExtractor:
    """Extract typed knowledge chunks from conversation text using Haiku."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model
        self.client = anthropic.AsyncAnthropic()

    async def extract(self, conversation_text: str) -> list[KnowledgeChunk]:
        """Extract knowledge chunks from a conversation transcript."""
        if not conversation_text.strip():
            return []

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(conversation=conversation_text[:8000]),
                    }
                ],
            )

            raw_text = response.content[0].text.strip()

            # Handle markdown code blocks in response
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                # Remove first and last lines (```json and ```)
                lines = [ln for ln in lines if not ln.strip().startswith("```")]
                raw_text = "\n".join(lines)

            data = json.loads(raw_text)
            if not isinstance(data, list):
                return []

            chunks = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                chunk_type = item.get("chunk_type", "fact")
                if chunk_type not in VALID_CHUNK_TYPES:
                    chunk_type = "fact"

                text = item.get("text", "").strip()
                if not text:
                    continue

                relation_type = item.get("relation_type")
                if relation_type and relation_type not in VALID_RELATIONS:
                    relation_type = None

                chunks.append(
                    KnowledgeChunk(
                        chunk_type=chunk_type,
                        text=text,
                        entities=item.get("entities", []) or [],
                        related_to=item.get("related_to", []) or [],
                        relation_type=relation_type,
                    )
                )
            return chunks

        except json.JSONDecodeError:
            logger.warning("Knowledge extraction returned invalid JSON", exc_info=True)
            return []
        except Exception:
            logger.warning("Knowledge extraction failed", exc_info=True)
            return []

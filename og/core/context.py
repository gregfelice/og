"""Layered system prompt builder: AGENTS.md + SOUL.md + TOOLS.md + skills + memory + contradictions."""

from __future__ import annotations

import logging
from pathlib import Path

from og.memory.manager import Memory
from og.memory.pg import PgMemory
from og.skills.loader import Skill, SkillRegistry

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Composes layered system prompts from markdown sources."""

    def __init__(
        self,
        prompts_dir: Path,
        memory: Memory | PgMemory,
        skill_registry: SkillRegistry,
    ):
        self.prompts_dir = Path(prompts_dir)
        self.memory = memory
        self.skill_registry = skill_registry

    def _read_prompt(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    async def build(
        self,
        message: str,
        matched_skills: list[Skill],
        entities: list[str] | None = None,
    ) -> str:
        sections = []

        # Layer 1: Agent identity
        agents_md = self._read_prompt("AGENTS.md")
        if agents_md:
            sections.append(agents_md)

        # Layer 2: Behavioral guidelines
        soul_md = self._read_prompt("SOUL.md")
        if soul_md:
            sections.append(soul_md)

        # Layer 3: Tool descriptions
        tools_md = self._read_prompt("TOOLS.md")
        if tools_md:
            sections.append(tools_md)

        # Layer 4: Skill catalog (always present)
        all_skills = self.skill_registry.skills
        if all_skills:
            catalog = "# Available Skills\n\n"
            for skill in all_skills:
                triggers = ", ".join(f'"{t}"' for t in skill.triggers)
                catalog += f"- **{skill.name}**: {skill.description} (triggers: {triggers})\n"
            sections.append(catalog)

        # Layer 5: Matched skill instructions (only when triggered)
        if matched_skills:
            skills_section = (
                "# Active Skills\n\nThe following skills are relevant to this request:\n"
            )
            for skill in matched_skills:
                skills_section += f"\n---\n\n{skill.instructions}\n"
            sections.append(skills_section)

        # Layer 6: Memory context
        memory_content = await self.memory.load_memory(message)
        if memory_content:
            sections.append(
                f"# Memory\n\nPersisted facts from previous sessions:\n\n{memory_content}"
            )

        # Layer 7: Contradiction warnings (when graph is available)
        if entities and isinstance(self.memory, PgMemory) and self.memory.graph is not None:
            try:
                contradictions = await self.memory.graph.find_contradictions(entities)
                if contradictions:
                    warnings = "# Contradiction Warnings\n\n"
                    warnings += (
                        "The following stored knowledge items may contradict each other:\n\n"
                    )
                    for c in contradictions:
                        warnings += f"- **A:** {c['statement_a']}\n  **B:** {c['statement_b']}\n\n"
                    sections.append(warnings)
            except Exception:
                logger.debug("Contradiction check failed", exc_info=True)

        return "\n\n---\n\n".join(sections)

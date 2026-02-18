"""Layered system prompt builder: AGENTS.md + SOUL.md + TOOLS.md + skills + memory."""

from __future__ import annotations

from pathlib import Path

from og.memory.manager import Memory
from og.skills.loader import Skill, SkillRegistry


class ContextBuilder:
    """Composes layered system prompts from markdown sources."""

    def __init__(self, prompts_dir: Path, memory: Memory, skill_registry: SkillRegistry):
        self.prompts_dir = Path(prompts_dir)
        self.memory = memory
        self.skill_registry = skill_registry

    def _read_prompt(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def build(self, message: str, matched_skills: list[Skill]) -> str:
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
            skills_section = "# Active Skills\n\nThe following skills are relevant to this request:\n"
            for skill in matched_skills:
                skills_section += f"\n---\n\n{skill.instructions}\n"
            sections.append(skills_section)

        # Layer 5: Memory context
        memory_content = self.memory.load_memory()
        if memory_content:
            sections.append(f"# Memory\n\nPersisted facts from previous sessions:\n\n{memory_content}")

        return "\n\n---\n\n".join(sections)

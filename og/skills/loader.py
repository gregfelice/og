"""YAML frontmatter + Markdown skill parser with selective injection."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import frontmatter


@dataclass
class Skill:
    name: str
    triggers: list[str]
    description: str
    instructions: str
    path: Path = field(repr=False)


class SkillRegistry:
    """Discovers and matches skills from SKILL.md files."""

    def __init__(self, skill_dirs: list[Path] | None = None):
        self.skills: list[Skill] = []
        if skill_dirs:
            for d in skill_dirs:
                self._discover(d)

    def _discover(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for skill_file in sorted(directory.rglob("SKILL.md")):
            skill = self._parse(skill_file)
            if skill:
                self.skills.append(skill)

    @staticmethod
    def _parse(path: Path) -> Skill | None:
        try:
            post = frontmatter.load(str(path))
        except Exception:
            return None
        meta = post.metadata
        if not meta.get("name") or not meta.get("triggers"):
            return None
        return Skill(
            name=meta["name"],
            triggers=[t.lower() for t in meta["triggers"]],
            description=meta.get("description", ""),
            instructions=post.content,
            path=path,
        )

    def match(self, message: str) -> list[Skill]:
        msg_lower = message.lower()
        matched = []
        for skill in self.skills:
            if any(trigger in msg_lower for trigger in skill.triggers):
                matched.append(skill)
        return matched

    def get(self, name: str) -> Skill | None:
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

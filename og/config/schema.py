"""Configuration schema with Pydantic BaseSettings."""

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 4096
    temperature: float = 0.7
    budget_limit: float = 5.00  # USD spending cap


class SessionConfig(BaseModel):
    storage_dir: Path = Path.home() / ".og" / "sessions"
    default_session: str = "default"


class SkillsConfig(BaseModel):
    dirs: list[Path] = []
    enabled: bool = True


class MemoryConfig(BaseModel):
    storage_dir: Path = Path.home() / ".og" / "memory"
    memory_file: str = "MEMORY.md"
    daily_logs_dir: str = "daily"


class ToolsConfig(BaseModel):
    bash_timeout: int = 30
    confirm_destructive: bool = True


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OG_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm: LLMConfig = LLMConfig()
    session: SessionConfig = SessionConfig()
    skills: SkillsConfig = SkillsConfig()
    memory: MemoryConfig = MemoryConfig()
    tools: ToolsConfig = ToolsConfig()
    prompts_dir: Path = Path("prompts")

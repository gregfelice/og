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
    project_id: str = "default"


class DatabaseConfig(BaseModel):
    host: str = "localhost"
    port: int = 5432
    name: str = "og"
    user: str = "og"
    password: str = "og"
    min_pool: int = 2
    max_pool: int = 10

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class EmbeddingConfig(BaseModel):
    model: str = "mxbai-embed-large"
    dimensions: int = 1024
    ollama_base_url: str = "http://localhost:11434/v1"


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
    db: DatabaseConfig = DatabaseConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    prompts_dir: Path = Path("prompts")

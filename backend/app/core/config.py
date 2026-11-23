from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    """后端统一配置，全部来自环境变量 / backend/.env。"""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    app_name: str = "AI 智播课堂"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    log_level: str = "INFO"

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    checkpointer_backend: str = "sqlite"
    langgraph_checkpoint_db: str = "./data/langgraph_checkpoints.db"
    langgraph_store_db: str = "./data/langgraph_store.db"

    # SSE 多进程广播：配置 REDIS_URL 后使用 Redis Pub/Sub，留空则退化为进程内广播
    redis_url: str = ""
    event_channel_prefix: str = "classroom:sse:"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_thinking_enabled: bool = False

    max_output_tokens: int = 800
    max_context_tokens: int = 3000
    task_token_budget: int = 12000
    task_max_model_calls: int = 8
    task_max_messages: int = 12
    task_max_turns: int = 10
    task_max_seconds: int = 120

    memory_retrieval_limit: int = 3
    memory_retrieval_min_score: float = 0.35
    memory_extraction_enabled: bool = True
    memory_extraction_transcript_chars: int = 600

    experience_extraction_enabled: bool = True
    experience_extraction_transcript_chars: int = 700
    experience_extraction_max_per_agent: int = 2
    experience_retrieval_limit: int = 3
    experience_retrieval_min_score: float = 0.4

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path | None:
        if not self.is_sqlite:
            return None
        raw = self.database_url.split("///", 1)[-1]
        path = Path(raw)
        if not path.is_absolute():
            path = (BACKEND_DIR / raw).resolve()
        return path

    @property
    def sync_database_url(self) -> str:
        """Alembic 用的同步 URL。"""
        return (
            self.database_url.replace("+aiosqlite", "")
            .replace("+asyncpg", "+psycopg")
        )

    @property
    def model_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    def ensure_data_dir(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = self.sqlite_path
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

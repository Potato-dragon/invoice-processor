"""Configuration loaded exclusively from environment variables."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = "change-me"
    database_url: str = "postgresql+psycopg://invoice:invoice@db:5432/invoice"
    redis_url: str = "redis://redis:6379/0"
    storage_dir: str = "/data/storage"
    gemini_api_key: str | None = None
    llm_primary_model: str = "Gemma 4"
    llm_fallback_model: str = "Gemini Flash-Lite"
    llm_fake: bool = False
    max_upload_mb: int = Field(default=50, gt=0)
    max_pages: int = Field(default=1500, gt=0)
    ocr_dpi: int = Field(default=300, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()

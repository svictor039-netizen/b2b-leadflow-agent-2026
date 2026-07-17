from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "B2B LeadFlow Agent"
    app_version: str = Field(default="0.7.0-stage6", alias="APP_VERSION")
    environment: str = "development"
    debug: bool = False

    database_url: str = Field(
        default="postgresql://leadflow:leadflow@postgres:5432/leadflow",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(
        default="redis://redis:6379/0",
        alias="REDIS_URL",
    )

    frontend_origin: str = Field(
        default="http://localhost:5173",
        alias="FRONTEND_ORIGIN",
    )

    system_stop_all: bool = Field(default=False, alias="SYSTEM_STOP_ALL")

    # Stage 6 placeholders — real/live must stay disabled
    real_email_provider_enabled: bool = Field(default=False, alias="REAL_EMAIL_PROVIDER_ENABLED")
    live_outreach_enabled: bool = Field(default=False, alias="LIVE_OUTREACH_ENABLED")
    provider_api_key: str = Field(default="", alias="PROVIDER_API_KEY")
    provider_sender_email: str = Field(default="", alias="PROVIDER_SENDER_EMAIL")
    provider_sender_domain: str = Field(default="", alias="PROVIDER_SENDER_DOMAIN")
    provider_daily_limit: int = Field(default=0, alias="PROVIDER_DAILY_LIMIT")

    celery_broker_url: str | None = Field(default=None, alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(default=None, alias="CELERY_RESULT_BACKEND")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Application settings, loaded from environment / .env."""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "api/.env", "../.env"),
        extra="ignore",
    )

    app_name: str = "Human in the Loop"
    environment: Literal["development", "production"] = "development"
    # Comma-separated list of allowed browser origins.
    cors_origins: str = "http://localhost:3000"

    # Postgres in every real environment. The sqlite+aiosqlite fallback exists
    # so the API boots on a laptop with no database daemon running.
    database_url: str = "sqlite+aiosqlite:///./hitl.db"
    # Alembic owns the schema in production. create_all stays available for
    # local dev and tests, where a one-command start matters more.
    auto_create_schema: bool = True
    # Unset => background jobs run in-process instead of via an arq worker.
    redis_url: str | None = None

    # --- auth --------------------------------------------------------------
    # Required in every environment so reloads/workers share a stable signing key.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # --- model providers ---------------------------------------------------
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    # Server-side refusal fallbacks (beta). Disable if your org lacks the beta.
    anthropic_enable_fallbacks: bool = True
    openai_api_key: str | None = None
    # Whatever chat-completions model your account has access to.
    openai_model: str = "gpt-5"

    # --- search ------------------------------------------------------------
    tavily_api_key: str | None = None

    # --- spend caps (per research task) ------------------------------------
    # These are the difference between a demo link and a surprise invoice.
    max_tool_iterations: int = 12
    max_searches_per_task: int = 8
    max_output_tokens_per_task: int = 60_000
    max_tasks_per_user_per_day: int = 25

    # --- per-IP throttling on unauthenticated endpoints -------------------
    rate_limit_enabled: bool = True
    rate_limit_register_per_hour: int = 5
    rate_limit_login_per_15_min: int = 10

    # --- data retention ---------------------------------------------------
    # "Save every search the user ever made" is a promise about their data.
    # 0 keeps history forever; any positive value purges tasks older than that
    # many days on a schedule. Whatever this is set to, say so in the README.
    data_retention_days: int = 0

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        placeholders = ("change-me", "dev-secret", "placeholder")
        normalized = self.jwt_secret.casefold()
        if (
            len(self.jwt_secret) < 32
            or self.jwt_secret != self.jwt_secret.strip()
            or any(value in normalized for value in placeholders)
            or len(set(self.jwt_secret)) < 16
        ):
            raise ValueError(
                "JWT_SECRET must be a stable, randomly generated value of at least "
                "32 characters (for example, secrets.token_urlsafe(48))"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

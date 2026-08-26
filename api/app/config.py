"""Application configuration and environment settings.

This module defines the central `Settings` class using Pydantic Settings.
Settings are dynamically loaded from environment variables and `.env` files.
It provides typed configuration for:
  - Application lifecycle and environment (development vs. production)
  - CORS policies and allowed origins
  - Database connectivity (PostgreSQL in production, SQLite fallback for local development)
  - Background task execution (in-process asyncio vs. Redis-backed Arq workers)
  - Authentication and JWT parameters
  - Multi-provider LLM credentials and default model configurations
  - Open-weight model server presets and token pricing overrides
  - Web search API integration (Tavily vs. offline stub)
  - Spend caps and token/iteration safeguards
  - Per-IP rate limiting policies
  - Data retention and periodic cleanup windows
"""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything configurable, resolved from the environment and .env files.

    Environment variables win over .env, and later files in `env_file` win over
    earlier ones - worth remembering when a root .env and api/.env disagree.
    """
    model_config = SettingsConfigDict(
        env_file=(".env", "api/.env", "../.env"),
        extra="ignore",
    )

    # --- Application & Environment -----------------------------------------
    # Name of the application displayed in API root and docs metadata
    app_name: str = "Human in the Loop"
    # Runtime environment: determines security strictness and dev conveniences
    environment: Literal["development", "production"] = "development"
    # Comma-separated list of allowed browser origins for CORS middleware
    cors_origins: str = "http://localhost:3000"

    # --- Database & Persistence --------------------------------------------
    # Postgres in every real environment. The sqlite+aiosqlite fallback exists
    # so the API boots on a laptop with no database daemon running.
    database_url: str = "sqlite+aiosqlite:///./hitl.db"
    # Alembic owns the schema in production. create_all stays available for
    # local dev and tests, where a one-command start matters more.
    auto_create_schema: bool = True
    # Redis connection URL for background job dispatch via Arq.
    # Unset => background jobs run in-process instead of via an arq worker.
    redis_url: str | None = None

    # --- Auth & Cryptography -----------------------------------------------
    # Secret key for HMAC signing of JWT tokens.
    # Required in every environment so reloads/workers share a stable signing key.
    jwt_secret: str = ""
    # Cryptographic signing algorithm for JWT access tokens
    jwt_algorithm: str = "HS256"
    # Token expiration lifespan in minutes (default is 7 days)
    jwt_expire_minutes: int = 60 * 24 * 7

    # --- Model Providers ---------------------------------------------------
    # Hosted APIs, plus any OpenAI-compatible server for open-weight models.
    # Preset names double as base-URL shorthands (app/llm/openai_compatible.py).
    llm_provider: Literal[
        "anthropic", "openai", "gemini",
        # open weights, your hardware
        "ollama", "llamacpp", "lmstudio", "vllm",
        # open weights, hosted
        "openrouter", "groq", "together", "fireworks",
        # any other OpenAI-compatible endpoint; needs OPEN_MODEL_BASE_URL
        "open",
    ] = "gemini"
    # API key and model selection for Anthropic Claude provider
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    # Server-side refusal fallbacks (beta). Disable if your org lacks the beta.
    anthropic_enable_fallbacks: bool = True
    # API key and model selection for OpenAI provider
    openai_api_key: str | None = None
    # Whatever chat-completions model your account has access to.
    openai_model: str = "gpt-5"
    # API key and model selection for Google Gemini provider
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.6-flash"

    # --- Open-Weight Models (Ollama, vLLM, OpenRouter, Groq, ...) ----------
    # Which server to talk to; defaults to LLM_PROVIDER when it names a preset.
    open_model_preset: str | None = None
    # Only needed for an endpoint that is not one of the known presets.
    open_model_base_url: str | None = None
    # Local servers ignore this; hosted ones require it.
    open_model_api_key: str | None = None
    # e.g. "llama3.1:8b" (Ollama), "meta-llama/llama-3.3-70b-instruct" (OpenRouter)
    open_model_name: str = "llama3.1:8b"
    # USD per 1M tokens. Zero is correct for a model on your own hardware - the
    # approval gate should say $0.00, not guess a price.
    open_model_price_input: float = 0.0
    open_model_price_output: float = 0.0

    # --- Search Engine Integration -----------------------------------------
    # Tavily API key for live web search queries. If unset, falls back to offline stub search.
    tavily_api_key: str | None = None

    # --- Spend Caps & Safeguards (Per Research Task) -----------------------
    # These are the difference between a demo link and a surprise invoice.
    # Maximum conversational turns in the research loop per task
    max_tool_iterations: int = 12
    # Maximum individual web search queries permitted per task
    max_searches_per_task: int = 8
    # Hard cumulative output token ceiling per task across all turns
    max_output_tokens_per_task: int = 60_000
    # Maximum research tasks a single user can create per 24-hour window
    max_tasks_per_user_per_day: int = 25

    # --- Per-IP Throttling on Unauthenticated Endpoints --------------------
    # Enables in-memory sliding window rate limiting on register and login
    rate_limit_enabled: bool = True
    # Maximum registration attempts allowed per IP address per hour
    rate_limit_register_per_hour: int = 5
    # Maximum login attempts allowed per IP address per 15-minute window
    rate_limit_login_per_15_min: int = 10

    # --- Data Retention & Lifecycle ----------------------------------------
    # "Save every search the user ever made" is a promise about their data.
    # 0 keeps history forever; any positive value purges tasks older than that
    # many days on a schedule. Whatever this is set to, say so in the README.
    data_retention_days: int = 0

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        """Refuse to start with unsafe defaults or weak secrets in production.
        
        Validates that JWT_SECRET is adequately long (>= 32 characters), does not
        contain well-known placeholder strings, and exhibits sufficient character entropy.
        """
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
        """CORS origins, parsed from the comma-separated setting.
        
        Returns:
            A list of trimmed origin URLs allowed to make cross-origin requests.
        """
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton.
    
    Reads environment variables and .env files once on initial call and caches
    the parsed `Settings` instance for the process lifetime.
    
    Returns:
        The cached Settings configuration instance.
    """
    return Settings()


# Global application settings instance for convenient direct imports
settings = get_settings()

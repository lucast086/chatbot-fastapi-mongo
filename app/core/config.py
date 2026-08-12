"""Application configuration.

Loaded once from the environment (and `.env` if present) and cached with
`get_settings()`. Every value has a default that lets the application boot and
be used — the API key is the single exception, and its absence degrades
generation rather than preventing startup.

Credentials are `SecretStr` so they cannot leak into a log line or a `repr()` by
accident; call `.get_secret_value()` at the point the raw value is actually
needed.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    app_env: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- MongoDB -----------------------------------------------------------
    # The default points at localhost so the test suite and a host-side run work
    # without configuration. docker-compose.yml overrides it with the service
    # name. SecretStr because a real deployment embeds credentials in this URI.
    mongo_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongo_db: str = "chatbot"

    # --- Model provider ----------------------------------------------------
    # Empty by default and deliberately not validated at startup: the
    # application is expected to boot without it. `provider_configured` below is
    # what the health check and the frontend banner read.
    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter's `:free` models are rotated and retired, so this is a default
    # to be overridden rather than a constant to be relied on. The README says
    # where the current list lives.
    openrouter_model: str = "google/gemma-4-31b-it:free"
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    # An answer cap. Without one a runaway or reasoning-heavy model can
    # produce until the context window ends, and a single document over
    # MongoDB's 16MB limit would fail the write for the whole turn.
    max_output_tokens: int = Field(default=2048, gt=0)

    # --- Conversation behaviour --------------------------------------------
    system_prompt: str = "You are a helpful assistant. Answer clearly and concisely."
    # How many previous messages are sent with each request. A window by message
    # count, not by tokens — a real token budget is listed in the README as
    # future work.
    history_limit: int = Field(default=20, gt=0)
    max_message_length: int = Field(default=8000, gt=0)
    # One extra provider call after the first turn of a conversation, to replace
    # the truncated first message with a real title. Off-switch provided because
    # it doubles the requests a first turn costs, which matters on a free tier.
    generate_titles: bool = True

    @property
    def provider_configured(self) -> bool:
        return bool(self.openrouter_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

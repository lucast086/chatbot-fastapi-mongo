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
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    mongo_uri: SecretStr = SecretStr("mongodb://localhost:27017")
    mongo_db: str = "chatbot"

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models: Annotated[list[str], NoDecode] = Field(
        default=[
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "inclusionai/ling-3.0-tiny:free",
        ],
        min_length=1,
    )
    request_timeout_seconds: float = Field(default=60.0, gt=0)
    first_token_timeout_seconds: float = Field(default=20.0, gt=0)
    max_output_tokens: int = Field(default=2048, gt=0)

    system_prompt: str = "You are a helpful assistant. Answer clearly and concisely."
    history_limit: int = Field(default=20, gt=0)
    max_message_length: int = Field(default=8000, gt=0)
    max_history_chars: int = Field(default=24_000, gt=0)
    generate_titles: bool = True

    @field_validator("openrouter_models", mode="before")
    @classmethod
    def split_comma_separated(cls, value: object) -> object:
        """Accept a comma-separated string for the model list.

        Pairs with the `NoDecode` annotation on the field: pydantic-settings
        JSON-decodes complex types straight from the environment before any
        validator runs, so without it a plain string fails to parse before this
        is reached. Asking a .env file for JSON would be a hostile contract.
        """
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def provider_configured(self) -> bool:
        return bool(self.openrouter_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

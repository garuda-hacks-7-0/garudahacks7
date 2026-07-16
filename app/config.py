from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TanggapTani"
    database_url: str = "sqlite:///./triage_mock.db"
    seed_demo_data: bool = True

    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-5-mini"
    openrouter_fallback_models: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 25.0
    app_public_url: str = "http://localhost:8000"

    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def openrouter_models(self) -> list[str]:
        return [
            model.strip()
            for model in self.openrouter_fallback_models.split(",")
            if model.strip() and model.strip() != self.openrouter_model
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


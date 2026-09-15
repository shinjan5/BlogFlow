from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str
    openrouter_model: str = "openai/gpt-oss-120b:free"

    database_url: str

    cors_allow_origins: str = "*"

    environment: str = "development"

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_allow_origins.strip() == "*":
            return ["*"]

        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
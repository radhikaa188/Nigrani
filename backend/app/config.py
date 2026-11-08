from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str | None = None
    REDIS_URL: str | None = None
    JWT_SECRET: str | None = None
    MODEL_ADAPTER: str | None = None
    OLLAMA_URL: str | None = None
    OLLAMA_MODEL: str | None = None
    GITHUB_WEBHOOK_SECRET: str | None = None
    SANDBOX_TIMEOUT_SECONDS: int | None = None
    SANDBOX_MEMORY_MB: int | None = None


settings = Settings()

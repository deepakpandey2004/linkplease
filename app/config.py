# app/config.py

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    # App
    app_env: str = "development"

    # Database
    database_url: str

    # PseudoGram API
    pseudogram_api_key: str
    pseudogram_base_url: str = "https://pseudogram-api.onrender.com"

    # Retry settings
    max_retries: int = 5
    retry_backoff_base: int = 2

    # Rate limiting
    rate_limit_max: int = 10
    rate_limit_window: int = 60

    # Worker intervals
    dm_worker_interval: float = 1.0
    poll_interval: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
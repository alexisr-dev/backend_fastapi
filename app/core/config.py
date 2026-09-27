from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "backend_fastapi"
    debug: bool = False

    db_name: str = "restaurante"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_host: str = "localhost"
    db_port: int = 5432
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    jwt_secret: str = "shared-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"

    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174"

    rate_limit_pedidos: int = 30
    rate_limit_ventana_segundos: int = 60

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origins_list(self) -> list[str]:
        return [origen.strip() for origen in self.cors_origins.split(",") if origen.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

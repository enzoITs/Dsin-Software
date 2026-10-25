from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://atalaia:atalaia@localhost:5433/atalaia"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    webhook_url: str = ""
    seed_equipamentos: int = 20000
    uploads_dir: str = "uploads"
    scheduler_enabled: bool = True
    # Canal de eventos da central. Vazio: entrega em memória, no próprio processo.
    redis_url: str = ""


settings = Settings()

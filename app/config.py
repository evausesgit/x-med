"""Configuration centrale (lue depuis l'environnement / .env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://xmed:xmed@localhost:5432/xmed"
    data_dir: str = "/home/geekette/data/pubmed"

    # Modèles d'embedding actifs (clés du registre embeddings)
    embedding_models: str = "medcpt,bge_m3"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    openai_api_key: str | None = None

    # Mode « PubMed d'abord » : recherche live E-utilities + construction de la
    # requête PubMed via le CLI codex (pas de clé API). Voir app/services/.
    ncbi_api_key: str | None = None
    ncbi_tool: str = "x-med"
    ncbi_email: str | None = None
    codex_bin: str = "codex"
    codex_model: str = "gpt-5.4"
    codex_abstract_timeout: int = 900

    # Notification Hermes/Telegram lorsqu'une recherche PubMed/Codex est lancée.
    # `telegram` cible le home channel Hermes, donc le DM Eva par défaut sur cette machine.
    search_notify_enabled: bool = True
    search_notify_target: str = "telegram"
    search_notify_hermes_bin: str = "hermes"
    search_notify_timeout: int = 20

    @property
    def embedding_model_list(self) -> list[str]:
        return [m.strip() for m in self.embedding_models.split(",") if m.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

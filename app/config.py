"""Configuration centrale (lue depuis l'environnement / .env)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://xmed:xmed@localhost:5432/xmed"
    # Base corpus (miroir PubMed, lecture seule côté API). Non renseignée →
    # repli sur `database_url` : les deux mondes vivent dans la même base
    # (infra monolithique actuelle). Voir app/db.py et PLAN_BASES_SEPAREES.md.
    corpus_database_url: str | None = None
    data_dir: str = "/home/geekette/data/pubmed"

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
    # Retour à gpt-5.4 sur tous les postes (requête PubMed, jugement, critique,
    # traduction) : c'est le modèle sur lequel le pipeline a été réglé et mesuré.
    # Le knob `codex_model_translate` reste séparé — il permet de re-router la
    # seule traduction sur un modèle moins cher sans toucher au reste.
    codex_model: str = "gpt-5.4"
    codex_model_translate: str = "gpt-5.4"
    # Effort de raisonnement : high sur tous les postes, traduction comprise —
    # c'est le régime sous lequel le pipeline tournait avant le 23/07, celui sur
    # lequel la qualité a été jugée. Il reste PINNÉ par appel : sans le flag,
    # codex irait lire l'effort dans le config.toml du CODEX_HOME ambiant, un
    # fichier qui n'appartient pas à x-med (« high » aujourd'hui côté hôte, mais
    # rien ne le garantit, et le défaut du CLI serait « medium »). Même valeur
    # qu'avant, donc, mais imposée par x-med au lieu d'être subie.
    codex_reasoning: str = "high"
    codex_reasoning_translate: str = "high"
    codex_abstract_timeout: int = 900

    # Table étroite de recherche FTS (`article_search`) : fenêtre glissante des
    # dernières années, maintenue chaude en RAM. Le pré-filtre du pipeline PubMed
    # est routé dessus quand la borne basse de la recherche est dans la fenêtre
    # (sinon on retombe sur la table complète `articles`). La largeur de la fenêtre
    # est définie UNE seule fois côté SQL (`article_search_min_year()`, migration
    # 0006) — le routage l'interroge, pas de knob applicatif qui pourrait diverger.
    # `use_narrow_search` reste False tant que le backfill initial n'est pas fait
    # (sinon on servirait des résultats d'une table incomplète). Voir la migration
    # 0006 et scripts/backfill_article_search.py.
    use_narrow_search: bool = False

    # Garde-fou du pré-filtre local (FTS sur ~25 M d'articles) : au-delà de ce
    # délai, Postgres annule la requête et la recherche continue avec PubMed seul.
    # Monté à 2 min pour l'essai « mesurer le vrai temps » (base censée être chaude
    # via pg_prewarm) ; le bouton stop du front couvre le cas « ça traîne trop ».
    local_search_timeout_ms: int = 120_000

    # Notification Hermes/Telegram lorsqu'une recherche PubMed/Codex est lancée.
    # `telegram` cible le home channel Hermes, donc le DM Eva par défaut sur cette machine.
    search_notify_enabled: bool = True
    search_notify_target: str = "telegram"
    search_notify_hermes_bin: str = "hermes"
    search_notify_timeout: int = 20

    # Envoi direct via l'API Telegram Bot (conteneurs Coolify : le CLI hermes
    # n'y existe pas). Si les deux variables sont renseignées, elles priment
    # sur le CLI hermes ; sinon repli sur hermes (dev local).
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

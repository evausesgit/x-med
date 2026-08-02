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
    # Répartition par tâche (comparatif Artificial Analysis, juillet 2026) :
    # - Terra : même prix que gpt-5.4 mais plus intelligent (Index 55 vs 51) et
    #   ~13 % plus rapide → requête PubMed, jugement, critique.
    # - Luna : l'intelligence de gpt-5.4 (Index 51) pour 2,5× moins cher et
    #   ~47 % plus rapide → traduction (le poste le plus gourmand en output).
    codex_model: str = "gpt-5.6-terra"
    codex_model_translate: str = "gpt-5.6-luna"
    # Effort de raisonnement PINNÉ par appel : sans ça, codex hérite du
    # config.toml du CODEX_HOME ambiant (« high » sur le poste de dev via la
    # config Hermes, indéterminé en prod) — la traduction tournait en high
    # sans raison. medium = défaut OpenAI, suffisant pour requête/jugement ;
    # low pour la traduction (tâche mécanique, gros volume d'output).
    codex_reasoning: str = "medium"
    codex_reasoning_translate: str = "low"
    codex_abstract_timeout: int = 900

    # Table étroite de recherche FTS (`article_search`) : fenêtre glissante des
    # dernières années, maintenue chaude en RAM. Le pré-filtre du pipeline PubMed
    # est routé dessus quand la borne basse de la recherche est dans la fenêtre
    # (sinon on retombe sur la table complète `articles`). La largeur de la fenêtre
    # est définie UNE seule fois côté SQL (`article_search_min_year()`, migration
    # 0006) — le routage l'interroge, pas de knob applicatif qui pourrait diverger.
    # `use_narrow_search` restait False tant que le backfill initial n'était pas
    # fait (sinon on servirait des résultats d'une table incomplète). Il l'est :
    # `article_search` compte exactement autant de lignes que `articles` sur la
    # fenêtre (3 459 665 des deux côtés, vérifié le 2026-08-02) — le miroir est
    # complet, le routage est activé. Voir la migration 0006 et
    # scripts/backfill_article_search.py.
    #
    # Ce n'est pas un simple confort : le pré-filtre passe l'essentiel de son temps
    # à détoaster les tsvectors des lignes trouvées, pour les classer par ts_rank.
    # Sur `articles` le TOAST fait 28 Go et reste froid ; sur `article_search`, 2,5 Go
    # qui tiennent en cache. Même requête, mêmes 3 concepts en ET, fenêtre 2025-2026 :
    # 11,1 s sur `articles` contre 0,12 s sur `article_search`.
    use_narrow_search: bool = True

    # Garde-fou du pré-filtre local (FTS sur ~25 M d'articles) : au-delà de ce
    # délai, Postgres annule la requête et la recherche continue avec PubMed seul.
    # C'est le budget TOTAL de l'échelle de relâchement (app/api/search.py).
    # Ramené de 2 min à 15 s : le pré-filtre interroge maintenant les concepts en
    # ET, et les requêtes saines mesurées tiennent en 0,4 à 2 s. Au-delà, ce n'est
    # plus « le sujet est large » mais une anomalie — mieux vaut rendre la main
    # vite que faire attendre le médecin 2 min pour un abandon.
    local_search_timeout_ms: int = 15_000

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

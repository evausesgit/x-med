#!/usr/bin/env bash
# Régénère le pool d'annotation (table eval_pool + bench/pool_fr.csv) dès que
# le job d'embedding en cours (scripts.embed_corpus) est terminé.
#
# À lancer depuis la copie qui a le venv ML (torch + modèles) et le .env,
# c'est-à-dire ~/projects/x-med :
#   nohup bash scripts/refresh_eval_pool.sh > /home/geekette/data/refresh_pool.log 2>&1 &
#
# Déroulé :
#   1. attend la fin de scripts.embed_corpus (vérification toutes les 10 min) ;
#   2. affiche la couverture d'embedding bge-m3 des articles 2025+ avec abstract
#      (alerte si < 95 % : le job s'est probablement arrêté avant la fin) ;
#   3. lance scripts.build_pool (k=20) : union plein-texte + sémantique sur les
#      requêtes de bench/queries_fr.json, restreinte au corpus vectorisé.
# Ensuite : annotation par les médecins sur /annotate, puis
#   uv run python -m scripts.build_pool --compile   -> bench/gold_fr.json
set -e
cd "$(dirname "$0")/.."

while pgrep -f "scripts.embed_corpus" > /dev/null; do
  echo "$(date '+%F %T') embedding en cours — nouvelle vérification dans 10 min"
  sleep 600
done

echo "$(date '+%F %T') plus de job d'embedding actif — couverture :"
uv run python - <<'EOF'
from sqlalchemy import text

from app.db import SessionLocal

with SessionLocal() as s:
    total, done = s.execute(text(
        """
        SELECT
          (SELECT count(*) FROM articles
            WHERE pub_year >= 2025 AND abstract IS NOT NULL AND abstract <> ''),
          (SELECT count(*) FROM emb_bge_m3 e JOIN articles a ON a.pmid = e.pmid
            WHERE a.pub_year >= 2025)
        """
    )).one()
ratio = done / max(total, 1)
print(f"  bge-m3 : {done}/{total} articles 2025+ avec abstract ({ratio:.0%})")
if ratio < 0.95:
    print("  ATTENTION : couverture < 95 % — le job s'est peut-être arrêté avant la fin.")
    print("  Le pool sera généré quand même ; relancer embed_corpus puis ce script si besoin.")
EOF

echo "$(date '+%F %T') régénération du pool d'annotation…"
uv run python -m scripts.build_pool --k 20

echo "$(date '+%F %T') terminé. Prochaines étapes :"
echo "  1. annotation des médecins sur /annotate (grades 0/1/2)"
echo "  2. uv run python -m scripts.build_pool --compile   # -> bench/gold_fr.json"
echo "  3. uv run python -m scripts.run_benchmark           # -> leaderboard"

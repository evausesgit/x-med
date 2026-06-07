"""Calcule les embeddings des articles et les écrit dans les tables emb_*.

Usage :
    uv run python -m scripts.embed_corpus --model bge_m3 --limit 5000
    uv run python -m scripts.embed_corpus --model medcpt --limit 5000
    uv run python -m scripts.embed_corpus --model all --limit 5000 --index
    # Corpus d'évaluation thématique (gynéco + ophtalmo) :
    uv run python -m scripts.embed_corpus --model all --theme gyneco ophtalmo --limit 20000 --index

Stratégie : les articles sans embedding, les plus récents d'abord
(ORDER BY pub_year DESC). Le texte = titre + abstract (titre seul si pas d'abstract).
Avec --theme / --mesh-any, on ne prend que les articles dont les tags MeSH
recoupent (&&) la liste correspondante (corpus d'évaluation ciblé).
"""

from __future__ import annotations

import argparse
import time

import psycopg
from pgvector.psycopg import register_vector

from app.config import settings
from app.services.embeddings import REGISTRY, get_model

# Filtres thématiques par tags MeSH (listes curées : on évite les motifs ILIKE
# qui attrapent des faux positifs comme « Television »/« Cell Division » pour
# « vision »/« division »). On embedde les articles dont mesh_terms recoupe (&&)
# l'une de ces listes — pour constituer un corpus d'évaluation ciblé.
THEMES: dict[str, list[str]] = {
    "gyneco": [
        "Pregnancy", "Pregnancy Complications", "Pregnancy Complications, Infectious",
        "Pregnancy in Diabetics", "Pregnancy Trimester, First", "Pregnancy Trimester, Second",
        "Pregnancy Trimester, Third", "Pregnancy, Ectopic", "Pregnancy, Multiple",
        "Uterus", "Uterine Cervical Neoplasms", "Uterine Neoplasms", "Uterine Diseases",
        "Uterine Contraction", "Uterine Hemorrhage", "Cervix Uteri", "Uterine Cervical Diseases",
        "Placenta", "Placenta Diseases", "Labor, Obstetric", "Delivery, Obstetric",
        "Obstetric Labor Complications", "Obstetrics", "Gynecology", "Ovary",
        "Ovarian Neoplasms", "Ovarian Follicle", "Ovarian Diseases", "Vagina", "Vaginal Smears",
        "Vulva", "Menstruation", "Menstruation Disturbances", "Endometrium", "Endometriosis",
        "Genital Diseases, Female", "Genital Neoplasms, Female", "Fallopian Tubes", "Menopause",
        "Amenorrhea", "Dysmenorrhea", "Infertility, Female", "Abortion, Spontaneous",
        "Abortion, Induced", "Prenatal Diagnosis", "Fetal Diseases",
    ],
    "ophtalmo": [
        "Ophthalmology", "Eye", "Eye Diseases", "Eye Neoplasms", "Eye Injuries", "Eye Movements",
        "Retina", "Retinal Diseases", "Retinal Detachment", "Retinal Vessels", "Glaucoma",
        "Intraocular Pressure", "Cornea", "Corneal Diseases", "Corneal Transplantation",
        "Cataract", "Cataract Extraction", "Lens, Crystalline", "Vision Disorders",
        "Vision, Ocular", "Vitreous Body", "Optic Nerve", "Optic Nerve Diseases", "Conjunctiva",
        "Conjunctivitis", "Uvea", "Uveitis", "Macula Lutea", "Macular Degeneration", "Eyelids",
        "Lacrimal Apparatus", "Refractive Errors", "Myopia", "Strabismus", "Visual Acuity",
        "Ocular Hypertension", "Choroid", "Sclera", "Iris", "Pupil", "Diabetic Retinopathy",
    ],
}


def _dsn() -> str:
    # psycopg.connect veut "postgresql://", pas "postgresql+psycopg://"
    return settings.database_url.replace("+psycopg", "")


def _doc_text(title: str | None, abstract: str | None) -> str:
    title = title or ""
    return f"{title}\n{abstract}" if abstract else title


def embed_model(
    model_name: str,
    limit: int,
    batch: int,
    make_index: bool,
    mesh: list[str] | None = None,
    require_abstract: bool = False,
) -> None:
    model = get_model(model_name)
    conn = psycopg.connect(_dsn())
    register_vector(conn)

    # Filtre thématique optionnel : articles dont les tags MeSH recoupent la liste.
    mesh_clause = "AND a.mesh_terms && %(mesh)s::text[]" if mesh else ""
    # N'embedder que les articles avec abstract (un embedding de titre seul est peu fiable).
    abstract_clause = (
        "AND a.abstract IS NOT NULL AND length(a.abstract) > 0" if require_abstract else ""
    )
    params = {"limit": limit, "mesh": mesh}

    # Articles pas encore embeddés pour ce modèle, plus récents d'abord
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.pmid, a.title, a.abstract
            FROM articles a
            LEFT JOIN {model.table} e ON e.pmid = a.pmid
            WHERE e.pmid IS NULL
            {mesh_clause}
            {abstract_clause}
            ORDER BY a.pub_year DESC NULLS LAST, a.pmid DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()

    if not rows:
        print(f"[{model_name}] rien à embedder.")
    else:
        print(f"[{model_name}] {len(rows)} articles à embedder…")
        t0 = time.time()
        done = 0
        for i in range(0, len(rows), batch):
            chunk = rows[i : i + batch]
            texts = [_doc_text(t, a) for _, t, a in chunk]
            vecs = model.encode_doc(texts)
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {model.table} (pmid, v) VALUES (%s, %s) "
                    f"ON CONFLICT (pmid) DO UPDATE SET v = EXCLUDED.v",
                    [(pmid, vecs[j]) for j, (pmid, _, _) in enumerate(chunk)],
                )
            conn.commit()
            done += len(chunk)
            rate = done / (time.time() - t0)
            print(f"  [{model_name}] {done}/{len(rows)} ({rate:.0f}/s)", flush=True)

    if make_index:
        print(f"[{model_name}] création de l'index HNSW…")
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {model.table}_hnsw "
                f"ON {model.table} USING hnsw (v vector_cosine_ops) "
                f"WITH (m = 16, ef_construction = 64)"
            )
        conn.commit()
        print(f"[{model_name}] index OK.")

    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="all", help="medcpt | bge_m3 | all")
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--index", action="store_true", help="créer l'index HNSW après")
    ap.add_argument(
        "--theme", nargs="*", choices=list(THEMES), default=[],
        help="filtre thématique MeSH (ex. : --theme gyneco ophtalmo)",
    )
    ap.add_argument(
        "--mesh-any", nargs="*", default=[],
        help="tags MeSH supplémentaires à inclure (en plus de --theme)",
    )
    ap.add_argument(
        "--require-abstract", action="store_true",
        help="n'embedder que les articles avec abstract (titre seul exclu)",
    )
    args = ap.parse_args()

    # Union des descripteurs MeSH des thèmes choisis + ceux passés à la main.
    mesh: list[str] = []
    for t in args.theme:
        mesh.extend(THEMES[t])
    mesh.extend(args.mesh_any)
    mesh = sorted(set(mesh)) or None
    if mesh:
        print(f"Filtre thématique : {len(mesh)} tags MeSH ({', '.join(args.theme) or 'mesh-any'})")

    models = list(REGISTRY) if args.model == "all" else [args.model]
    for name in models:
        embed_model(name, args.limit, args.batch, args.index, mesh, args.require_abstract)


if __name__ == "__main__":
    main()

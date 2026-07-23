"""Digest on-demand : la pipeline de recherche v2 nourrie par le profil du médecin.

Pas de pipeline dédiée ni de cron (décision Eva : on-demand seulement, pour ne
pas brûler de tokens) : quand le médecin connecté clique « Générer mon digest »,
on compose une query depuis son profil (metaprompt + facettes, voir
`services/digest_query.py`) et on la fait avaler telle quelle par
`_run_deep_search` via la même machinerie SSE que la recherche classique.

La query composée ne transite JAMAIS par l'URL (le profil clinique n'a rien à
faire dans les logs du proxy) : le front n'envoie que `days` et le jeton
d'annulation, le backend reconstruit tout.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.me import Identity, _find_doctor, current_identity
from app.api.search import DeepSearchRequest, deep_search_sse
from app.db import get_session
from app.services.digest_query import build_digest_query, digest_usage_label
from app.services.usage_log import record_usage

router = APIRouter()

# 30 jours par défaut (7 jours donne trop souvent zéro article sur les niches) ;
# le front propose 7/30/90 sans jamais relancer automatiquement une recherche.
DIGEST_DAYS_DEFAULT = 30


@router.get("/digest/stream")
def digest_stream(
    request: Request,
    days: int = Query(default=DIGEST_DAYS_DEFAULT, ge=1, le=365),
    k_pubmed: int = Query(default=20, ge=1, le=200),
    judge_batch: int = Query(default=50, ge=10, le=100),
    local_token: str | None = Query(default=None, max_length=64),
    ident: Identity = Depends(current_identity),
    session: Session = Depends(get_session),
):
    """Génère le digest du médecin connecté, en SSE — mêmes événements que
    /search/pubmed/deep/stream (`log`* → `result` → `translations`* → `complete`),
    donc même code front pour le déroulé live, l'arrêt et les traductions.

    La fenêtre couvre les `days` derniers jours côté PubMed (précis au jour) ;
    le fonds local complète, avec exclusion des articles dont la date prouve
    qu'ils sont hors fenêtre (cf. `_window_keep`). `require_builder=True` : sans
    query-builder GPT-5.4, le digest échoue proprement plutôt que d'envoyer le
    metaprompt français brut à PubMed.
    """
    doctor = _find_doctor(session, ident)
    if doctor is None or doctor.profile is None:
        raise HTTPException(
            404, "Complétez votre profil pour générer votre digest personnalisé."
        )
    record_usage(
        request,
        "digest.run",
        query=digest_usage_label(doctor.profile, days),
        params={"days": days, "k_pubmed": k_pubmed},
    )
    return deep_search_sse(
        DeepSearchRequest(
            query=build_digest_query(doctor, doctor.profile),
            date_from=(date.today() - timedelta(days=days)).isoformat(),
            k_pubmed=k_pubmed,
            rrf=True,
            judge_batch=judge_batch,
            local_token=local_token,
            require_builder=True,
        ),
        notif_query=digest_usage_label(doctor.profile, days),
    )

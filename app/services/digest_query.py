"""Composition de la « query » du digest à partir du profil médecin.

Le digest on-demand ne crée PAS de pipeline dédiée : il fabrique une phrase de
recherche (metaprompt + profil sérialisé) et la fait avaler par la pipeline v2
existante (`_run_deep_search`), exactement comme une question tapée par le
médecin. Le query-builder GPT-5.4 en tire la requête PubMed, et le juge score
« pertinence pour ce profil » au lieu de « pertinence pour cette question ».

Décision de design (accordée avec Codex) : un seul champ query, zéro branche
dans la pipeline — le mode digest n'existe que dans la composition de l'input.
"""

from __future__ import annotations

from app.models import Doctor, DoctorProfile

# Libellés FR des niveaux de preuve (grille evidence_level 1-4 du projet).
_EVIDENCE_LABELS = {
    1: "méta-analyses et essais randomisés (niveau 1)",
    2: "études contrôlées (niveaux 1-2)",
    3: "études observationnelles ou mieux (niveaux 1-3)",
    4: "tout niveau de preuve",
}


def _join(items: list[str] | None) -> str | None:
    cleaned = [i.strip() for i in (items or []) if i and i.strip()]
    return ", ".join(cleaned) if cleaned else None


def build_digest_query(doctor: Doctor, profile: DoctorProfile) -> str:
    """Metaprompt + profil lisible → la « question clinique » du digest.

    La phrase d'intention vient en tête (c'est elle qui cadre le query-builder
    et le juge), puis chaque facette non vide du profil sur sa propre ligne.
    Les facettes vides sont omises pour ne pas diluer la requête PubMed.
    """
    lines = [
        "Digest de veille bibliographique pour un médecin : sélectionner les "
        "publications récentes les plus importantes et cliniquement utiles "
        "pour le profil suivant (pratique quotidienne, pas de question unique).",
        f"Spécialité principale : {profile.specialty_main}.",
    ]
    facets = [
        ("Sous-spécialités", _join(profile.subspecialties)),
        ("Pathologies suivies", _join(profile.pathologies)),
        ("Traitements et interventions d'intérêt", _join(profile.treatments)),
        ("Types d'études privilégiés", _join(profile.study_types)),
        ("Journaux de référence", _join(profile.preferred_journals)),
        ("Termes MeSH complémentaires", _join(profile.mesh_terms_extra)),
        ("Mots-clés complémentaires", _join(profile.keywords_extra)),
    ]
    lines += [f"{label} : {value}." for label, value in facets if value]
    if profile.min_evidence_level in _EVIDENCE_LABELS:
        lines.append(
            f"Privilégier les {_EVIDENCE_LABELS[profile.min_evidence_level]}."
        )
    lines.append(
        "Les types d'études, journaux et niveaux de preuve ci-dessus sont des "
        "préférences de PRIORISATION, pas des filtres bloquants : ne pas les "
        "transformer en clauses restrictives de la requête PubMed."
    )
    return "\n".join(lines)


def digest_usage_label(profile: DoctorProfile, days: int) -> str:
    """Libellé compact du digest pour le journal d'usage et la notif Telegram.

    On n'y met JAMAIS le metaprompt intégral : `usage_events` persiste la query
    telle quelle, et la notification l'affiche — le profil clinique complet n'a
    rien à faire dans ces canaux.
    """
    return f"Digest on-demand · {profile.specialty_main} · {days} j"

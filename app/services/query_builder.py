"""Construction d'une requête PubMed à partir d'une question clinique FR.

Plutôt qu'une clé API, on shelle le CLI `codex` (`codex exec`) avec
`--output-schema` pour obtenir une sortie JSON structurée. C'est l'étape clé du
mode « PubMed d'abord » : sans elle, envoyer la question française brute à PubMed
(lexical/MeSH) reproduit les travers du moteur lexical (mots banals qui dominent).

Si codex est absent, non authentifié, ou trop lent, on lève QueryBuildError et
l'appelant retombe sur la question brute.

**Le modèle ne rédige plus la requête ; il décrit le sens, le code rédige.**
Auparavant on lui demandait une chaîne PubMed complète — un objet à syntaxe
libre : quel concept en `[MeSH]` ou en `[tiab]`, quel emboîtement de parenthèses,
quel ordre. Des centaines de formes sont valides, il en tirait une au sort à
chaque appel. Mesuré en août 2026 sur trois appels identiques (même modèle, même
effort) : seuls **12,4 articles sur 20** étaient communs aux trois, et le nombre
de résultats PubMed variait jusqu'à **5,6×** sur la même question. Un
contre-témoin a écarté la piste du modèle : l'écart entre deux modèles
différents n'est pas distinguable de l'écart entre deux appels identiques
(Mann-Whitney p = 0,32). La cause n'est pas le modèle, c'est la liberté qu'on
lui laisse. Le CLI codex n'expose ni température ni graine : le déterminisme ne
peut donc venir que du **rétrécissement de l'espace de sortie**.

Le modèle garde ce qu'il fait bien — traduire, trouver les synonymes cliniques,
les noms de molécules. Le code fait le reste, et le fait toujours pareil :

1. `mesh_vocab.resolve` valide chaque descripteur contre le thésaurus réel et
   rétrograde en `[tiab]` ce qui n'existe pas (16 % des termes émis) ;
2. les termes sont dédoublonnés puis **triés** — deux réponses de même sens
   produisent donc une requête octet pour octet identique ;
3. `compose_pubmed_query` assemble `(concept 1) AND (concept 2)`.

Le point 3 ne perd rien : sur 32 requêtes réellement produites par le modèle,
31 étaient déjà exactement de cette forme (aucun filtre de type de publication,
de date ou de langue ; un seul `NOT`).
"""

from __future__ import annotations

import logging

from app.services import mesh_vocab
from app.services.codex_cli import CodexCliError, CodexUsage, run_codex

log = logging.getLogger(__name__)

# Un concept = une contrainte de la question (la maladie, le traitement, la
# population…). `mesh` et `synonyms_en` décrivent LE MÊME concept : ils partent
# donc en OU dans le même bloc, et les blocs sont reliés par ET.
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label_fr": {"type": "string"},
                    "mesh": {"type": "array", "items": {"type": "string"}},
                    "synonyms_en": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label_fr", "mesh", "synonyms_en"],
            },
        },
    },
    "required": ["concepts"],
}

# Deux consignes qui tirent dans des sens opposés, et c'est voulu :
#
#   ÉLARGIR   *à l'intérieur* d'un concept — plus de synonymes = plus de rappel
#             sans perte de sens (« HFpEF », « diastolic heart failure »… parlent
#             tous de la même maladie). C'est ce qui remplace l'union de
#             plusieurs tirages : un seul appel, mais large.
#   NE PAS    *entre* les concepts — remplacer « insuffisance cardiaque à FEVG
#   ÉLARGIR   préservée » par « insuffisance cardiaque » change la population
#             étudiée. Observé en vrai : deux appels sur la même question, l'un
#             gardait le descripteur spécifique, l'autre le généralisait.
#
# Sans la seconde consigne, la première pousse mécaniquement à la dilution : le
# mouvement naturel pour « ramener plus de résultats » est de lâcher la contrainte.
_PROMPT = (
    "Tu es expert en recherche bibliographique biomédicale (PubMed). "
    "Découpe la question clinique française suivante en CONCEPTS. Question : {q}\n"
    "\n"
    "RÈGLE 1 — FIDÉLITÉ (impérative). N'élargis JAMAIS un concept à sa version "
    "générale et n'en supprime aucun : si la question porte sur l'insuffisance "
    "cardiaque à fraction d'éjection préservée, le concept est cette forme "
    "précise, pas « insuffisance cardiaque » ; si elle précise « chez la "
    "personne âgée », cette restriction doit apparaître. Une contrainte perdue "
    "donne au médecin des articles hors sujet.\n"
    "\n"
    "RÈGLE 2 — UN CONCEPT = UNE ENTITÉ. Les concepts sont les entités "
    "concrètes : la maladie (sous sa forme précise, stade et sous-type "
    "compris), l'intervention ou l'exposition, la population si elle est "
    "restreinte, le comparateur s'il est nommé. Deux interdits :\n"
    "  (a) JAMAIS de concept méthodologique — efficacité, résultat, tolérance, "
    "pronostic, prise en charge, traitement au sens général, dépistage au sens "
    "général. Ces mots sont dans presque tous les articles cliniques : ils ne "
    "filtrent rien de fiable et font varier le nombre de résultats d'un facteur "
    "10. C'est l'IA qui lit les résumés ensuite qui jugera de l'efficacité ;\n"
    "  (b) JAMAIS deux concepts dont l'un est déjà contenu dans l'autre — si un "
    "concept est « mélanome de stade III », ne crée pas en plus un concept "
    "« mélanome » : le ET des deux ne restreint rien et écarte des articles.\n"
    "En pratique 2 concepts, 3 au maximum. Un seul concept est acceptable si la "
    "question ne porte que sur une entité.\n"
    "\n"
    "RÈGLE 3 — LARGEUR, mais en partant du plus courant. Pour chaque concept, "
    "commence par TOUTES les formes courantes — le terme usuel, son sigle et "
    "les variantes typographiques du sigle (HFpEF, HF-pEF), singulier et "
    "pluriel, orthographes britannique et américaine — puis ajoute les formes "
    "rares : terminologie savante, anciennes dénominations encore employées, "
    "DCI et noms commerciaux et codes de développement des molécules, classe "
    "pharmacologique. Les formes courantes ne doivent JAMAIS manquer : elles "
    "portent l'essentiel des articles, et une liste qui les remplace par des "
    "tournures rares change la recherche du tout au tout. Vise 8 à 15 "
    "synonymes : ils sont en OU, donc un synonyme rare ne coûte rien et c'est "
    "souvent lui qui ramène l'article que personne ne trouve.\n"
    "\n"
    "RÈGLE 4 — MeSH. Dans `mesh`, mets le NOM EXACT du descripteur MeSH "
    "officiel, pas un terme d'entrée ni un synonyme : le thésaurus range "
    "« Chemotherapy, Adjuvant » et non « Adjuvant Chemotherapy », « SARS-CoV-2 » "
    "et non « Severe Acute Respiratory Syndrome Coronavirus 2 ». Sans "
    "qualificatif (pas de « /therapy ») et sans tag. Dans le doute, laisse "
    "`mesh` vide : un descripteur inexistant ne remonte rien. Les molécules "
    "récentes ne sont pas des descripteurs — laisse-les dans `synonyms_en`.\n"
    "\n"
    "N'écris ni tag [MeSH]/[tiab], ni opérateur AND/OR, ni parenthèses : la "
    "requête est assemblée par le programme. Classe les concepts du plus "
    "spécifique au plus général. Réponds uniquement via le schéma JSON imposé."
)


class QueryBuildError(RuntimeError):
    """codex indisponible, non authentifié, trop lent, ou sortie illisible."""


def is_usage_limit(text: str | None) -> bool:
    """Vrai si le message d'erreur codex indique un dépassement de quota GPT-5.6.

    Partagé par les 3 appels codex (requête, jugement, traduction) pour afficher
    un bandeau explicite à l'utilisateur plutôt qu'un « mode dégradé » silencieux.
    """
    t = (text or "").lower()
    return (
        "usage limit" in t
        or "hit your usage limit" in t
        or "purchase more credits" in t
        or "rate limit" in t
    )


def _clean(items) -> list[str]:
    """Termes non vides, sans doublon de casse, dans l'ordre d'apparition."""
    out: list[str] = []
    seen: set[str] = set()
    for t in items or []:
        if not isinstance(t, str):
            continue
        t = " ".join(t.split())
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def normalize_concepts(concepts) -> list[list[str]]:
    """Nettoie les groupes de synonymes : vides retirés, doublons écartés.

    Le pré-filtre local en fait un ET de OU : un groupe vide ou un terme blanc
    produirait une tsquery invalide, et un groupe dupliqué coûterait un ET inutile.
    Tolère aussi une chaîne à la place d'un groupe (codex peut aplatir un concept
    à un seul synonyme).
    """
    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for group in concepts or []:
        items = [group] if isinstance(group, str) else group
        if not isinstance(items, (list, tuple)):
            continue
        terms = _clean(items)
        key = tuple(sorted(t.lower() for t in terms))
        if terms and key not in seen:
            seen.add(key)
            out.append(terms)
    return out


def compose_pubmed_query(blocks: list[tuple[list[str], list[str]]]) -> str:
    """Assemble `(bloc 1) AND (bloc 2)` à partir de (descripteurs, termes libres).

    Deux garanties, l'une de justesse et l'autre de reproductibilité :

    - **tout est cité.** Vérifié contre PubMed : les guillemets ne changent aucun
      compte, y compris avec troncature (`"gliflozin*"[tiab]` = `gliflozin*[tiab]`
      = 433). Citer systématiquement retire donc une variation gratuite, et met à
      l'abri des expressions à plusieurs mots laissées nues par le modèle ;
    - **tout est trié.** L'ordre des synonymes dans un OU ne change pas le
      résultat mais changeait la chaîne : le tri rend deux réponses de même sens
      octet pour octet identiques (utile pour comparer, tracer, et mettre en
      cache plus tard).

    L'ordre des CONCEPTS, lui, est conservé : il est signifiant en aval (échelle
    de relâchement du pré-filtre local, qui retire les concepts les plus généraux
    en dernier).
    """
    parts: list[str] = []
    for mesh, tiab in blocks:
        clauses = [f'"{m}"[MeSH]' for m in sorted(mesh, key=str.lower)]
        clauses += [f'"{t}"[tiab]' for t in sorted(tiab, key=str.lower)]
        if clauses:
            parts.append("(" + " OR ".join(clauses) + ")")
    return " AND ".join(parts)


def build_from_concepts(concepts, session=None) -> dict:
    """Transforme la sortie du modèle en requête PubMed + viviers de mots-clés.

    Retourne le contrat attendu en aval : `pubmed_query` (assemblée ici, plus par
    le modèle), `concepts_en` (synonymes groupés, pour le ET du pré-filtre local),
    `keywords_en` (la même chose à plat) et `mesh_terms` (les descripteurs
    **validés**, sous leur nom officiel).

    `session` donne accès au thésaurus MeSH ; sans elle, aucun terme n'est
    validé ni rétrogradé (comportement historique).
    """
    blocks: list[tuple[list[str], list[str]]] = []
    groups: list[list[str]] = []
    mesh_ok: list[str] = []
    demoted: list[str] = []
    for c in concepts or []:
        if not isinstance(c, dict):
            continue
        proposed = _clean(c.get("mesh"))
        synonyms = _clean(c.get("synonyms_en"))
        if session is not None and proposed:
            valid, rejected = mesh_vocab.resolve(proposed, session)
        else:
            valid, rejected = proposed, []
        demoted += rejected
        mesh_ok += valid
        # Un descripteur refusé redevient un terme plein texte : il reste dans la
        # course au lieu de rendre 0 en silence.
        tiab = _clean(synonyms + rejected)
        if not valid and not tiab:
            continue
        blocks.append((valid, tiab))
        # Le vivier LOCAL reste en synonymes seuls : y injecter un nom de
        # descripteur (« Heart Failure ») ferait matcher des millions de lignes,
        # exactement ce que le passage au ET a corrigé.
        if tiab:
            groups.append(tiab)
    if demoted:
        # Tracé : c'est la mesure du problème (16 % des termes émis à l'origine).
        # Une dérive à la hausse signalerait un thésaurus périmé ou un prompt cassé.
        log.info("MeSH rétrogradés en [tiab] (inexistants au thésaurus) : %s", demoted)
    return {
        "pubmed_query": compose_pubmed_query(blocks),
        "concepts_en": normalize_concepts(groups),
        "keywords_en": _clean([t for g in groups for t in g]),
        "mesh_terms": _clean(mesh_ok),
        "mesh_rejected": _clean(demoted),
    }


def build_pubmed_query(
    question: str, timeout: int = 180, session=None
) -> tuple[dict, CodexUsage]:
    """Retourne ({pubmed_query, mesh_terms, keywords_en, concepts_en}, usage).

    Lève QueryBuildError si codex est absent, non authentifié, trop lent, ou muet.
    """
    try:
        data, usage = run_codex(_PROMPT.format(q=question), _SCHEMA, timeout)
    except CodexCliError as e:
        raise QueryBuildError(str(e)) from e
    out = build_from_concepts(data.get("concepts"), session)
    if not out["pubmed_query"]:
        raise QueryBuildError("aucun concept exploitable dans la sortie codex")
    return out, usage

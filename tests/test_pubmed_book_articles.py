"""PubMed ne publie pas que des articles de revue : il publie aussi des **livres**
(`<PubmedBookArticle>`), et c'est sous cette forme qu'arrivent une bonne partie des
recommandations de sociétés savantes — les guidelines NICE au premier chef.

Le parseur ne regardait que `<PubmedArticle>` : ces recommandations rendaient un
résumé vide, et un candidat sans résumé est écarté avant le jugement (le juge doit
lire le texte). Mesuré en vrai sur « recommandations de société savante pour la
bipolarité » : NICE « Bipolar disorder: assessment and management » (PMID 31556980)
était renvoyé par PubMed, avait bien un résumé, et n'a jamais été soumis au juge.

Même piège côté `esummary` : un livre laisse `title` et `source` VIDES (le titre est
dans `booktitle`, l'éditeur dans `publishername`). Sans repli, le médecin voyait un
PMID nu et le juge recevait un titre vide.

Aucun réseau : on injecte les réponses NCBI telles qu'elles arrivent réellement.
"""

import httpx

from app.services import pubmed_eutils as eut

# Les deux enveloppes côte à côte, comme dans une vraie réponse efetch mixte.
# Le PMID n'est PAS au même endroit : MedlineCitation/PMID pour l'article,
# BookDocument/PMID pour le livre — c'est tout l'objet du correctif.
EFETCH_XML = b"""<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">39194164</PMID>
      <Article>
        <ArticleTitle>Practice Guidelines for Bipolar Disorder by the JSMD</ArticleTitle>
        <Abstract><AbstractText>Recommandations japonaises.</AbstractText></Abstract>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedBookArticle>
    <BookDocument>
      <PMID Version="1">31556980</PMID>
      <Book><BookTitle>Bipolar disorder: assessment and management</BookTitle></Book>
      <Abstract>
        <AbstractText Label="OVERVIEW">This guideline covers recognising bipolar
        disorder.</AbstractText>
        <AbstractText Label="SCOPE">Adults, children and young people.</AbstractText>
      </Abstract>
    </BookDocument>
  </PubmedBookArticle>
</PubmedArticleSet>
"""

# Docsum réel d'un livre NICE : `title` et `source` vides, tout est ailleurs.
ESUMMARY_JSON = {
    "result": {
        "uids": ["31556980", "39194164"],
        "31556980": {
            "title": "",
            "booktitle": "Bipolar disorder: assessment and management",
            "source": "",
            "fulljournalname": "",
            "publishername": "National Institute for Health and Care Excellence (NICE)",
            "pubdate": "2025 Sep 2",
            "articleids": [],
        },
        "39194164": {
            "title": "Practice Guidelines for Bipolar Disorder by the JSMD.",
            "source": "Psychiatry Clin Neurosci",
            "fulljournalname": "Psychiatry and clinical neurosciences",
            "pubdate": "2024 Nov",
            "articleids": [{"idtype": "doi", "value": "10.1111/pcn.13725"}],
        },
    }
}


class _Response:
    def __init__(self, content=b"", payload=None):
        self.content = content
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    """Remplace httpx.Client comme gestionnaire de contexte, sans réseau."""

    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        return self._response


def _stub(monkeypatch, response):
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _Client(response))


def test_efetch_reads_book_abstracts(monkeypatch):
    """Le cœur du correctif : un livre a bien un résumé, on doit le lire."""
    _stub(monkeypatch, _Response(content=EFETCH_XML))
    out = eut.efetch_abstracts([39194164, 31556980])
    assert 31556980 in out, "la recommandation NICE ne doit plus disparaître"
    # Les sections structurées sont préservées comme pour un article de revue.
    assert out[31556980].startswith("OVERVIEW: This guideline covers")
    assert "SCOPE: Adults, children and young people." in out[31556980]


def test_efetch_still_reads_journal_articles(monkeypatch):
    """Non-régression : l'enveloppe historique reste lue, dans la même réponse."""
    _stub(monkeypatch, _Response(content=EFETCH_XML))
    out = eut.efetch_abstracts([39194164, 31556980])
    assert out[39194164] == "Recommandations japonaises."


def test_esummary_falls_back_to_book_title(monkeypatch):
    """Un livre n'a pas de `title` : sans repli, le juge reçoit un titre vide."""
    _stub(monkeypatch, _Response(payload=ESUMMARY_JSON))
    hits = eut.esummary([31556980, 39194164])
    assert hits[31556980].title == "Bipolar disorder: assessment and management"
    # Pas de revue pour un livre : l'éditeur tient ce rôle à l'affichage.
    assert hits[31556980].journal.startswith("National Institute for Health")
    assert hits[31556980].pub_year == 2025


def test_esummary_unchanged_for_journal_articles(monkeypatch):
    """Non-régression : un article de revue garde titre, revue et DOI d'origine."""
    _stub(monkeypatch, _Response(payload=ESUMMARY_JSON))
    h = eut.esummary([31556980, 39194164])[39194164]
    assert h.title == "Practice Guidelines for Bipolar Disorder by the JSMD"
    assert h.journal == "Psychiatry and clinical neurosciences"
    assert h.doi == "10.1111/pcn.13725"

"""Registre de modèles d'embedding (auto-hébergés).

Chaque modèle expose `encode_doc` (articles) et `encode_query` (requête médecin)
et renseigne sa table pgvector (`emb_*`) et sa dimension. Les imports lourds
(torch, transformers…) sont chargés paresseusement : importer ce module ne tire
pas torch tant qu'on n'embed pas réellement.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class EmbeddingModel(Protocol):
    name: str
    table: str
    dim: int

    def encode_doc(self, texts: list[str]) -> np.ndarray: ...
    def encode_query(self, texts: list[str]) -> np.ndarray: ...


class MedCPT:
    """MedCPT (NLM) — encodeurs article/requête distincts, 768 dims, anglais."""

    name = "medcpt"
    table = "emb_medcpt"
    dim = 768

    def __init__(self) -> None:
        self._art = self._art_tok = self._qry = self._qry_tok = None

    def _ensure(self) -> None:
        if self._art is not None:
            return
        from transformers import AutoModel, AutoTokenizer

        self._art_tok = AutoTokenizer.from_pretrained("ncats/MedCPT-Article-Encoder")
        self._art = AutoModel.from_pretrained("ncats/MedCPT-Article-Encoder").eval()
        self._qry_tok = AutoTokenizer.from_pretrained("ncats/MedCPT-Query-Encoder")
        self._qry = AutoModel.from_pretrained("ncats/MedCPT-Query-Encoder").eval()

    def _embed(self, model, tok, texts: list[str], max_length: int, batch: int = 32) -> np.ndarray:
        import torch

        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = tok(
                    texts[i : i + batch],
                    truncation=True,
                    padding=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                emb = model(**enc).last_hidden_state[:, 0, :]  # pooling CLS
                emb = torch.nn.functional.normalize(emb, p=2, dim=1)
                out.append(emb.cpu().numpy())
        return np.vstack(out).astype(np.float32)

    def encode_doc(self, texts: list[str]) -> np.ndarray:
        self._ensure()
        return self._embed(self._art, self._art_tok, texts, max_length=512)

    def encode_query(self, texts: list[str]) -> np.ndarray:
        self._ensure()
        return self._embed(self._qry, self._qry_tok, texts, max_length=64)


class BgeM3:
    """BAAI/bge-m3 — multilingue (FR/EN), 1024 dims, encodeur symétrique."""

    name = "bge_m3"
    table = "emb_bge_m3"
    dim = 1024

    def __init__(self) -> None:
        self._m = None

    def _ensure(self):
        if self._m is None:
            from sentence_transformers import SentenceTransformer

            self._m = SentenceTransformer("BAAI/bge-m3")
        return self._m

    def _encode(self, texts: list[str]) -> np.ndarray:
        m = self._ensure()
        return m.encode(
            texts, normalize_embeddings=True, batch_size=16, convert_to_numpy=True
        ).astype(np.float32)

    def encode_doc(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_query(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)


# Instances paresseuses (ne chargent rien tant qu'on n'appelle pas encode_*)
REGISTRY: dict[str, EmbeddingModel] = {
    "medcpt": MedCPT(),
    "bge_m3": BgeM3(),
}


def get_model(name: str) -> EmbeddingModel:
    if name not in REGISTRY:
        raise KeyError(f"Modèle d'embedding inconnu : {name!r} (dispo : {list(REGISTRY)})")
    return REGISTRY[name]

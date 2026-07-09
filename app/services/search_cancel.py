"""Annulation d'une recherche PubMed + IA en cours (bouton « Arrêter » du front).

Le front génère un jeton par recherche (déjà transmis au stream pour annuler la
requête FTS locale) ; `POST /search/pubmed/deep/stop/{token}` marque la recherche
comme annulée. L'annulation est coopérative :

- le sous-processus `codex` en cours est tué immédiatement (c'est lui qui porte
  l'essentiel du temps ET du coût — inutile de payer un jugement qu'on jette) ;
- le pipeline s'arrête au prochain événement de progression (`SearchCancelled`),
  ce qui couvre les phases courtes (esearch, efetch) sans les instrumenter.

Un seul process API (uvicorn) → un dict module suffit, pas besoin de Redis.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections import OrderedDict
from contextvars import ContextVar
from threading import Lock


class SearchCancelled(Exception):
    """La recherche a été arrêtée par l'utilisateur (pas une erreur)."""


def kill_proc_tree(proc: subprocess.Popen) -> None:
    """Tue le groupe de processus entier (codex lance des enfants : tuer le seul
    parent laisserait des orphelins qui gardent les pipes ouverts, et
    `communicate()` ne rendrait jamais la main). Suppose `start_new_session=True`
    au lancement ; à défaut, retombe sur un kill du seul processus."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        proc.kill()


class CancelState:
    """État d'annulation d'une recherche : drapeau + sous-processus codex courant."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._proc: subprocess.Popen | None = None

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            if self._proc is not None:
                kill_proc_tree(self._proc)

    def attach_proc(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc
            # Stop arrivé entre le lancement du process et son enregistrement.
            if self._cancelled:
                kill_proc_tree(proc)

    def detach_proc(self) -> None:
        with self._lock:
            self._proc = None

    def raise_if_cancelled(self) -> None:
        if self._cancelled:
            raise SearchCancelled


# Recherche en cours dans le thread courant : posée par le worker SSE, lue par
# `run_codex` — évite d'enfiler le jeton dans toutes les signatures intermédiaires
# (query_builder / judge / translate).
current_search: ContextVar[CancelState | None] = ContextVar("current_search", default=None)

_ACTIVE: dict[str, CancelState] = {}

# Jetons DÉJÀ démarrés (terminés, annulés, ou en cours). Sert de garde-fou contre la
# RELANCE d'une recherche par reconnexion : l'`EventSource` du navigateur se reconnecte
# tout seul dès que la connexion tombe (timeout proxy pendant le silence du jugement,
# hoquet réseau) en réutilisant la MÊME URL — donc le même jeton. Sans ce garde, chaque
# reconnexion relançait une recherche complète (nouvel appel codex) et laissait le
# `produce()` précédent tourner en orphelin → « ça relance une requête » / « les process
# ne s'arrêtent pas ». Une vraie nouvelle recherche a un jeton neuf (UUID) → jamais bloquée.
# Borné (OrderedDict façon LRU) car les jetons sont uniques et éphémères.
_SEEN: OrderedDict[str, None] = OrderedDict()
_SEEN_MAX = 4096


def register(token: str) -> CancelState | None:
    """Enregistre une nouvelle recherche. Renvoie `None` si le jeton a DÉJÀ servi
    (reconnexion SSE / relance) : l'appelant doit alors NE PAS démarrer de recherche."""
    if token in _SEEN:
        return None
    _SEEN[token] = None
    while len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)
    state = CancelState()
    _ACTIVE[token] = state
    return state


def unregister(token: str) -> None:
    # On retire de l'index des recherches actives, MAIS on garde le jeton dans `_SEEN`
    # (une reconnexion après la fin d'une recherche ne doit pas non plus relancer).
    _ACTIVE.pop(token, None)


def cancel(token: str) -> bool:
    """Annule la recherche identifiée par `token`. False si aucune en cours."""
    state = _ACTIVE.get(token)
    if state is None:
        return False
    state.cancel()
    return True

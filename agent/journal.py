"""Sauvegarde des conversations pour analyse ultérieure.

Deux niveaux, volontairement distincts :

- le **checkpointer** LangGraph (`conversations.db`) garde l'historique vivant
  de chaque fil, pour que la conversation survive à un rechargement de page ou
  à un redémarrage du serveur ;
- le **journal** ci-dessous fige une copie *immuable* d'une conversation au
  moment où tu la signales, avec la config qui l'a produite.

La distinction n'est pas cosmétique. Le checkpointer suit le fil : si tu
reposes la question, l'état change. Le journal, lui, doit encore montrer dans
six mois exactement ce que l'agent avait répondu ce jour-là, avec le prompt de
ce jour-là — c'est tout l'intérêt d'archiver une mauvaise réponse.

Le dump conserve les artefacts des recherches (notes remontées, scores,
mots-clés absents), pas seulement le texte : c'est là que se lit *pourquoi*
l'agent a mal répondu.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONVERSATIONS_DB = BASE_DIR / "conversations.db"

# Rôles lisibles : on relit ces dumps à l'œil nu.
_ROLES = {"human": "utilisateur", "ai": "agent", "tool": "outil", "system": "systeme"}


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(CONVERSATIONS_DB)
    db.row_factory = sqlite3.Row
    # Le checkpointer LangGraph écrit dans le même fichier depuis une
    # connexion asynchrone distincte. WAL permet aux deux de cohabiter.
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db() -> None:
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations_sauvees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                origine TEXT NOT NULL,
                motif TEXT NOT NULL DEFAULT '',
                trace_id TEXT,
                cree_le TEXT NOT NULL,
                config TEXT NOT NULL,
                echanges TEXT NOT NULL
            )
            """
        )


def _texte(message) -> str:
    """Le contenu textuel, que le modèle renvoie une chaîne ou des blocs.

    `text` est une propriété dans LangChain récent et une méthode dans les
    versions antérieures — on accepte les deux plutôt que de figer le dump sur
    une version de la bibliothèque.
    """
    texte = getattr(message, "text", None)
    if callable(texte):
        texte = texte()
    if isinstance(texte, str):
        return texte

    contenu = getattr(message, "content", "")
    if isinstance(contenu, str):
        return contenu
    return "".join(
        bloc.get("text", "")
        for bloc in contenu
        if isinstance(bloc, dict) and bloc.get("type") == "text"
    )


def normaliser(messages: list) -> list[dict]:
    """Messages LangChain → structures JSON relisibles à l'œil nu.

    On ne sérialise pas les objets LangChain bruts : leur format change d'une
    version à l'autre, et un dump qu'on ne sait plus relire ne sert à rien.
    """
    echanges = []
    for message in messages:
        echange = {
            "role": _ROLES.get(message.type, message.type),
            "contenu": _texte(message),
        }

        appels = getattr(message, "tool_calls", None)
        if appels:
            echange["recherches_demandees"] = [
                {"outil": a["name"], "args": a["args"]} for a in appels
            ]

        artefact = getattr(message, "artifact", None)
        if artefact:
            echange["resultats"] = artefact

        echanges.append(echange)
    return echanges


def sauvegarder(
    thread_id: str,
    messages: list,
    config: dict,
    motif: str = "",
    origine: str = "app",
    trace_id: str | None = None,
) -> dict:
    init_db()
    enregistrement = {
        "thread_id": thread_id,
        "origine": origine,
        "motif": motif.strip(),
        "trace_id": trace_id,
        "cree_le": datetime.now().isoformat(timespec="seconds"),
        "config": json.dumps(config, ensure_ascii=False),
        "echanges": json.dumps(normaliser(messages), ensure_ascii=False),
    }
    with get_db() as db:
        curseur = db.execute(
            """
            INSERT INTO conversations_sauvees
                (thread_id, origine, motif, trace_id, cree_le, config, echanges)
            VALUES (:thread_id, :origine, :motif, :trace_id, :cree_le, :config, :echanges)
            """,
            enregistrement,
        )
        identifiant = curseur.lastrowid
    return lire(identifiant)


def _ligne_en_dict(ligne: sqlite3.Row, complet: bool) -> dict:
    echanges = json.loads(ligne["echanges"])
    resume = {
        "id": ligne["id"],
        "thread_id": ligne["thread_id"],
        "origine": ligne["origine"],
        "motif": ligne["motif"],
        "trace_id": ligne["trace_id"],
        "cree_le": ligne["cree_le"],
        "config": json.loads(ligne["config"]),
        "nb_echanges": len(echanges),
        # Première question posée : c'est ce qui identifie une conversation
        # dans une liste, bien mieux qu'une date.
        "question": next(
            (e["contenu"] for e in echanges if e["role"] == "utilisateur"), ""
        ),
    }
    if complet:
        resume["echanges"] = echanges
    return resume


def lister() -> list[dict]:
    init_db()
    with get_db() as db:
        lignes = db.execute(
            "SELECT * FROM conversations_sauvees ORDER BY id DESC"
        ).fetchall()
    return [_ligne_en_dict(ligne, complet=False) for ligne in lignes]


def lire(identifiant: int) -> dict | None:
    init_db()
    with get_db() as db:
        ligne = db.execute(
            "SELECT * FROM conversations_sauvees WHERE id = ?", (identifiant,)
        ).fetchone()
    return _ligne_en_dict(ligne, complet=True) if ligne else None


def supprimer(identifiant: int) -> bool:
    init_db()
    with get_db() as db:
        curseur = db.execute(
            "DELETE FROM conversations_sauvees WHERE id = ?", (identifiant,)
        )
    return curseur.rowcount > 0

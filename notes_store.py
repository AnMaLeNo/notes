"""Cœur de l'application : base SQLite, embeddings et recherche sémantique.

Partagé par l'API HTTP (`app.py`) et par l'agent conversationnel (`agent/`).
Les deux tournent dans des processus distincts et chargent donc chacun leur
propre instance du modèle d'embedding — d'où le chargement paresseux.
"""

import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "notes.db"
MODELS_DIR = BASE_DIR / "models"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

SEARCH_LIMIT = 20
SCORE_THRESHOLD = 0.25

# Constante usuelle de la Reciprocal Rank Fusion : amortit l'écart entre les
# premiers rangs pour qu'un 1er d'une liste ne écrase pas un 2e de l'autre.
RRF_K = 60

_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    """Modèle d'embedding, chargé au premier appel (quelques secondes)."""
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(MODELS_DIR))
    return _model


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                embedding BLOB NOT NULL
            )
            """
        )


def embed(text: str) -> np.ndarray:
    """Embedding L2-normalisé (float32) — la similarité cosinus devient un produit scalaire."""
    vec = np.array(next(get_model().embed([text])), dtype=np.float32)
    return vec / np.linalg.norm(vec)


def note_row_to_dict(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "content": row["content"], "created_at": row["created_at"]}


def search_notes(
    query: str,
    limit: int = SEARCH_LIMIT,
    threshold: float = SCORE_THRESHOLD,
) -> list[dict]:
    """Notes les plus proches de `query` par le sens, triées par score décroissant."""
    query = query.strip()
    if not query:
        return []
    with get_db() as db:
        rows = db.execute("SELECT * FROM notes").fetchall()
    if not rows:
        return []
    query_vec = embed(query)
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), -1)
    scores = matrix @ query_vec
    order = np.argsort(scores)[::-1][:limit]
    return [
        {**note_row_to_dict(rows[i]), "score": round(float(scores[i]), 3)}
        for i in order
        if scores[i] >= threshold
    ]


# --- Recherche par mots-clés ------------------------------------------------

_MOT = re.compile(r"[a-z0-9]+")


def _normaliser(texte: str) -> str:
    """Minuscules sans accents — « Intermarché » rejoint « intermarche »."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _tokens(texte: str) -> list[str]:
    return _MOT.findall(_normaliser(texte))


def _contient(tokens_note: list[str], tokens_cle: list[str]) -> bool:
    """La suite `tokens_cle` apparaît-elle telle quelle dans `tokens_note` ?

    Le dernier token tolère un préfixe, ce qui absorbe les pluriels et les
    dérivations courantes : « workflow » trouve « workflows », « projet »
    trouve « projets ».
    """
    if not tokens_cle:
        return False
    n = len(tokens_cle)
    for i in range(len(tokens_note) - n + 1):
        fenetre = tokens_note[i : i + n]
        if fenetre[:-1] != tokens_cle[:-1]:
            continue
        note, cle = fenetre[-1], tokens_cle[-1]
        if note == cle or (len(cle) >= 4 and note.startswith(cle)):
            return True
    return False


def _correspondances(contenu: str, mots_cles: list[str]) -> list[str]:
    """Les mots-clés effectivement présents dans la note."""
    tokens_note = _tokens(contenu)
    return [m for m in mots_cles if _contient(tokens_note, _tokens(m))]


# --- Recherche hybride ------------------------------------------------------


def search_hybrid(
    query: str,
    mots_cles: list[str] | None = None,
    limit: int = SEARCH_LIMIT,
    threshold: float = SCORE_THRESHOLD,
) -> dict:
    """Fusionne la recherche sémantique et la recherche par mots-clés.

    Les deux signaux vivent sur des échelles incomparables (cosinus vs nombre
    de termes trouvés), donc on ne fusionne pas les scores mais les *rangs*,
    par Reciprocal Rank Fusion. Une note présente dans les deux classements
    cumule deux contributions et remonte naturellement au-dessus d'une note
    qui n'en satisfait qu'un seul : c'est là que se gagne la précision.

    Renvoie `{"notes": [...], "mots_cles_absents": [...]}` — les mots-clés
    introuvables dans *toute* la base sont un signal fort que l'information
    demandée n'existe pas.
    """
    mots_cles = [m for m in (mots_cles or []) if m.strip()]
    with get_db() as db:
        rows = db.execute("SELECT * FROM notes").fetchall()
    if not rows:
        return {"notes": [], "mots_cles_absents": mots_cles}

    semantique: dict[int, float] = {}
    if query.strip():
        query_vec = embed(query)
        matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
        matrix = matrix.reshape(len(rows), -1)
        scores = matrix @ query_vec
        semantique = {
            row["id"]: float(score)
            for row, score in zip(rows, scores)
            if score >= threshold
        }

    trouves: dict[int, list[str]] = {}
    for row in rows:
        correspondances = _correspondances(row["content"], mots_cles)
        if correspondances:
            trouves[row["id"]] = correspondances

    classement_semantique = sorted(semantique, key=semantique.get, reverse=True)
    classement_mots = sorted(
        trouves,
        key=lambda i: (len(trouves[i]), semantique.get(i, 0.0)),
        reverse=True,
    )

    fusion: dict[int, float] = defaultdict(float)
    for classement in (classement_semantique, classement_mots):
        for rang, note_id in enumerate(classement, start=1):
            fusion[note_id] += 1 / (RRF_K + rang)

    par_id = {r["id"]: r for r in rows}
    meilleurs = sorted(fusion, key=fusion.get, reverse=True)[:limit]
    notes = [
        {
            **note_row_to_dict(par_id[note_id]),
            "score": round(semantique.get(note_id, 0.0), 3),
            "mots_cles": trouves.get(note_id, []),
        }
        for note_id in meilleurs
    ]

    apparus = {m for liste in trouves.values() for m in liste}
    return {
        "notes": notes,
        "mots_cles_absents": [m for m in mots_cles if m not in apparus],
    }

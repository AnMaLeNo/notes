"""Cœur de l'application : base SQLite, embeddings et recherche sémantique.

Partagé par l'API HTTP (`app.py`) et par l'agent conversationnel (`agent/`).
Les deux tournent dans des processus distincts et chargent donc chacun leur
propre instance du modèle d'embedding — d'où le chargement paresseux.
"""

import sqlite3
from pathlib import Path

import numpy as np
from fastembed import TextEmbedding

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "notes.db"
MODELS_DIR = BASE_DIR / "models"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

SEARCH_LIMIT = 20
SCORE_THRESHOLD = 0.25

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

"""Notes app — prise de notes minimaliste avec recherche sémantique locale.

Lancement : .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8300

L'agent conversationnel vit à part, dans `chainlit_app.py`.
"""

from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from notes_store import (
    BASE_DIR,
    embed,
    get_db,
    get_model,
    init_db,
    note_row_to_dict,
    search_notes,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    get_model()
    yield


app = FastAPI(title="Notes", lifespan=lifespan)


class NoteIn(BaseModel):
    content: str


@app.post("/api/notes")
def create_note(note: NoteIn):
    content = note.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Note vide")
    vec = embed(content)
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO notes (content, embedding) VALUES (?, ?)",
            (content, vec.tobytes()),
        )
        row = db.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return note_row_to_dict(row)


@app.get("/api/notes")
def list_notes():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, content, created_at FROM notes ORDER BY id DESC"
        ).fetchall()
    return [note_row_to_dict(r) for r in rows]


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    with get_db() as db:
        cur = db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Note introuvable")
    return {"ok": True}


@app.get("/api/search")
def search(q: str):
    return search_notes(q)


@app.get("/api/map")
def map_notes():
    """Projette tous les embeddings en 3D par PCA — le front utilise (x, y) pour la vue 2D."""
    with get_db() as db:
        rows = db.execute("SELECT * FROM notes").fetchall()
    if not rows:
        return []
    matrix = np.frombuffer(b"".join(r["embedding"] for r in rows), dtype=np.float32)
    matrix = matrix.reshape(len(rows), -1)
    centered = matrix - matrix.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    coords = centered @ vt[:3].T
    if coords.shape[1] < 3:
        coords = np.pad(coords, ((0, 0), (0, 3 - coords.shape[1])))
    span = np.abs(coords).max(axis=0)
    span[span == 0] = 1.0
    coords = coords / span
    return [
        {
            **note_row_to_dict(r),
            "x": round(float(c[0]), 4),
            "y": round(float(c[1]), 4),
            "z": round(float(c[2]), 4),
        }
        for r, c in zip(rows, coords)
    ]


frontend_dist = BASE_DIR / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

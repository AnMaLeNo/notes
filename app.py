"""Notes app — prise de notes minimaliste avec recherche sémantique locale.

Lancement : .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8300

Sert l'API, le frontend, et l'agent conversationnel : l'interface Chainlit
est montée sur `/chat` et affichée dans l'onglet « Agent ». La même interface
reste lançable en autonome sur le port 8400 pour déboguer — un seul module de
chat (`chainlit_app.py`) derrière les deux.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from chainlit.utils import mount_chainlit
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Avant les imports de l'agent : ils lisent les variables d'env au chargement.
# Chemin explicite plutôt que la recherche par défaut, qui part du répertoire
# courant : lancer uvicorn depuis ailleurs ne doit pas priver l'agent de sa clé.
load_dotenv(Path(__file__).resolve().parent / ".env")

from agent import journal  # noqa: E402
from notes_store import (  # noqa: E402
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
    journal.init_db()
    # Chargé ici, et non par Chainlit : le module d'embedding est un singleton
    # partagé, donc l'agent monté sur /chat profite du même modèle.
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


# --- Conversations archivées ------------------------------------------------
#
# L'archivage lui-même se fait dans Chainlit (bouton « Signaler », voir
# `chainlit_app.py`), qui appelle `journal.sauvegarder` directement. Ici on ne
# fait que relire : c'est l'onglet « Archives » du frontend.


@app.get("/api/conversations")
def lister_conversations():
    return journal.lister()


@app.get("/api/conversations/{identifiant}")
def lire_conversation(identifiant: int):
    conversation = journal.lire(identifiant)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    return conversation


@app.delete("/api/conversations/{identifiant}")
def supprimer_conversation(identifiant: int):
    if not journal.supprimer(identifiant):
        raise HTTPException(status_code=404, detail="Conversation introuvable")
    return {"ok": True}


# --- Montages ---------------------------------------------------------------
#
# L'ordre compte : Starlette teste les routes dans l'ordre d'ajout, et le
# montage statique sur « / » avalerait tout ce qui vient après.

@app.get("/chat")
def chat_sans_slash():
    """Renvoie `/chat` vers `/chat/`.

    Chainlit installe un middleware qui répond 404 à tout ce qui ne commence
    pas exactement par son chemin de montage — y compris `/chat` nu, avant que
    Starlette n'ait pu rediriger. Sans cette route, taper l'adresse à la main
    tombe sur un 404 déroutant. Déclarée avant le montage : les routes sont
    testées dans l'ordre d'ajout.
    """
    return RedirectResponse("/chat/")


# L'interface de chat, affichée dans l'onglet « Agent » du frontend. C'est la
# même que sur le port 8400 : un seul module, deux points d'entrée.
mount_chainlit(app=app, target=str(BASE_DIR / "chainlit_app.py"), path="/chat")

frontend_dist = BASE_DIR / "frontend" / "dist"
if frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

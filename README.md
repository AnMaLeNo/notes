# Notes

Prise de notes minimaliste avec recherche sémantique locale.

Le texte de chaque note est transformé en vecteur d'embedding (modèle
multilingue, exécuté localement via [fastembed](https://github.com/qdrant/fastembed)),
ce qui permet une recherche par sens plutôt que par mot-clé. Les notes
peuvent aussi être visualisées sous forme de carte 2D ou 3D, où les notes
proches en signification apparaissent proches sur la carte (projection PCA
des embeddings).

## Stack

- **Backend** : FastAPI + SQLite, embeddings via `fastembed`
  (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)
- **Frontend** : React + Vite

## Prérequis

- Python 3.11+
- Node.js 18+

## Installation

```bash
# Backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Frontend
cd frontend
npm install
```

## Développement

```bash
# Backend (http://localhost:8300)
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8300 --reload

# Frontend (http://localhost:5173, proxy vers l'API)
cd frontend
npm run dev
```

## Build de production

```bash
cd frontend
npm run build
```

Le build (`frontend/dist`) est servi directement par FastAPI : une fois
généré, `uvicorn app:app` sert à la fois l'API et le frontend sur le même
port.

## API

| Méthode  | Route              | Description                              |
| -------- | ------------------ | ----------------------------------------- |
| `GET`    | `/api/notes`        | Liste toutes les notes                    |
| `POST`   | `/api/notes`        | Crée une note (`{ "content": "..." }`)    |
| `DELETE` | `/api/notes/{id}`   | Supprime une note                         |
| `GET`    | `/api/search?q=...` | Recherche sémantique (top 20, seuil 0.25) |
| `GET`    | `/api/map`          | Projection 2D/3D des embeddings (PCA)     |

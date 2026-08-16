# Notes

Prise de notes minimaliste avec recherche sémantique locale.

Le texte de chaque note est transformé en vecteur d'embedding (modèle
multilingue, exécuté localement via [fastembed](https://github.com/qdrant/fastembed)),
ce qui permet une recherche par sens plutôt que par mot-clé. Les notes
peuvent aussi être visualisées sous forme de carte 2D ou 3D, où les notes
proches en signification apparaissent proches sur la carte (projection PCA
des embeddings).

Un **agent conversationnel** (LangGraph + Gemini) sert d'interface de
recherche : il reformule la question en une requête adaptée à la recherche
vectorielle, puis répond à partir des notes trouvées.

## Stack

- **Backend** : FastAPI + SQLite, embeddings via `fastembed`
  (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)
- **Frontend** : React + Vite
- **Agent** : LangGraph + Gemini, interface [Chainlit](https://chainlit.io)

## Prérequis

- Python 3.11+
- Node.js 18+
- Une clé d'API Google Gemini (pour l'agent uniquement)

## Installation

```bash
# Backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Agent : renseigner la clé d'API
cp .env.example .env   # puis éditer GOOGLE_API_KEY

# Frontend
cd frontend
npm install
```

## Développement

```bash
# Backend (http://localhost:8300)
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8300 --reload

# Agent (http://localhost:8400)
.venv/bin/chainlit run chainlit_app.py -w --port 8400

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

## Agent

```
agent/
├── prompts.py   Prompt système (dont la technique de reformulation)
├── tools.py     Les outils. Pour l'instant : recherche_dans_les_notes
└── graph.py     Le graphe LangGraph et la configuration du modèle

chainlit_app.py  Interface de chat : streaming + Steps de débogage
notes_store.py   Base, embeddings et recherche — partagés avec l'API
```

Le graphe est une boucle ReAct minimale :

```
START → agent ──(veut un outil ?)──→ outils ──┐
          ↑                                   │
          └───────────────────────────────────┘
          └──(non)──→ END
```

Le cœur de l'agent est la **reformulation de la requête**. Une note est une
affirmation ; une question ne lui ressemble pas vectoriellement. L'agent
transforme donc « Combien de temps cuit la pizza 4 fromages d'Intermarché ? »
en « la pizza 4 fromages d'Intermarché cuit X minutes à Y degrés », ce qui
place la requête bien plus près de la note recherchée dans l'espace
d'embeddings.

Dans Chainlit, chaque appel d'outil apparaît comme une étape dépliable
montrant la requête formulée et les notes remontées avec leur score — c'est
la boucle de feedback pour ajuster le prompt.

### Faire évoluer

- **Nouvelle capacité** → un outil dans `agent/tools.py`, ajouté à `TOOLS`.
- **Nouvelle étape** (reranking, garde-fou, mémoire longue) → un nœud dans
  `agent/graph.py`.
- **Persistance des conversations** → remplacer `InMemorySaver` par un
  checkpointer SQLite dans `build_graph()`.

### Variables d'environnement

| Variable                      | Défaut             | Rôle                                        |
| ----------------------------- | ------------------ | ------------------------------------------- |
| `GOOGLE_API_KEY`              | —                  | Requise par l'agent (`GEMINI_API_KEY` marche aussi) |
| `NOTES_AGENT_MODEL`           | `gemini-3.1-flash-lite` | Modèle utilisé                              |
| `NOTES_AGENT_THINKING_BUDGET` | défaut du modèle   | Budget de réflexion : `0` = désactivé, `-1` = dynamique |

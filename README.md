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
├── prompts.py   Prompt système, en blocs composables
├── tools.py     Les outils. Pour l'instant : rechercher_dans_les_notes
└── graph.py     Le graphe LangGraph, le budget et la config du modèle

chainlit_app.py  Interface de chat : streaming + Steps de débogage
notes_store.py   Base, embeddings et recherche — partagés avec l'API
```

Le graphe est une boucle ReAct minimale, plafonnée :

```
START → agent ──(veut chercher ?)──→ recherches ──┐
          ↑                                       │
          └───────────────────────────────────────┘
          └──(non)──→ END
```

### 1. Reformuler la question

Une note est une affirmation ; une question ne lui ressemble pas
vectoriellement. L'agent transforme donc « Combien de temps cuit la pizza
4 fromages d'Intermarché ? » en « la pizza 4 fromages d'Intermarché cuit
X minutes à Y degrés », ce qui rapproche la requête de la note cherchée dans
l'espace d'embeddings.

### 2. Chercher sur deux axes

L'agent produit aussi des **mots-clés** (`["pizza", "4 fromages",
"Intermarché"]`). Deux recherches tournent alors en parallèle :

- **sémantique** — rattrape les synonymes et les fautes de frappe. Une note
  écrite « rasberrypies » répond à « Raspberry Pi » ;
- **mots-clés** — ancre la recherche sur ce qui ne se devine pas : noms
  propres, marques, chiffres. Comparaison sans accents ni casse, tolérante aux
  pluriels (« workflow » trouve « workflows »).

Les deux classements sont fusionnés par **Reciprocal Rank Fusion**. On fusionne
les rangs et non les scores, parce qu'un cosinus et un nombre de termes trouvés
ne vivent pas sur la même échelle. Une note qui satisfait les deux signaux
cumule deux contributions et passe devant : c'est là que se gagne la précision.

Les mots-clés introuvables dans toute la base sont signalés à l'agent — c'est
le signal le plus net que l'information n'existe pas.

### 3. Juger, puis recommencer

Après chaque recherche, l'agent décide si les résultats suffisent (scores
faibles ? aucun mot-clé trouvé ? sujet correct mais information absente ?) et
peut relancer une recherche reformulée.

Le budget est tenu par le **graphe**, pas par le prompt : au-delà de
`MAX_RECHERCHES`, l'appel de l'outil est interdit côté API et le prompt de
recherche est remplacé par un prompt de réponse seule. Une consigne se
négocie, pas un outil inaccessible.

> Deux pièges rencontrés, corrigés dans le code : sans outil, le modèle
> **invente une note** plutôt que d'admettre l'échec (d'où une interdiction
> explicite d'inventer) ; et tant que le prompt décrit l'outil, il tente de
> l'appeler quand même — Gemini renvoie alors `MALFORMED_FUNCTION_CALL`,
> c'est-à-dire une réponse vide (d'où le prompt découpé en blocs).

### Déboguer

Dans Chainlit, chaque recherche apparaît comme une étape dépliable montrant la
requête sémantique, les mots-clés, les notes remontées avec leur score et leurs
correspondances, et le compteur `recherche N/3`.

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
| `NOTES_AGENT_MAX_RECHERCHES`  | `3`                | Recherches autorisées par question          |
| `NOTES_AGENT_THINKING_BUDGET` | défaut du modèle   | Budget de réflexion : `0` = désactivé, `-1` = dynamique |

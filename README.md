# Notes

Prise de notes minimaliste avec recherche sémantique locale.

Le texte de chaque note est transformé en vecteur d'embedding (modèle
multilingue, exécuté localement via [fastembed](https://github.com/qdrant/fastembed)),
ce qui permet une recherche par sens plutôt que par mot-clé. Les notes
peuvent aussi être visualisées sous forme de carte 2D ou 3D, où les notes
proches en signification apparaissent proches sur la carte (projection PCA
des embeddings).

Un **agent conversationnel** (LangGraph + Gemini) complète la recherche :
il reformule la question en une requête adaptée à la recherche vectorielle,
puis répond à partir des notes trouvées. Son interface est
[Chainlit](https://chainlit.io), montée sur `/chat` et affichée dans l'onglet
« Agent » ; la même reste lançable en autonome sur le port 8400 pour
déboguer.

Les deux recherches cohabitent parce qu'elles ne servent pas au même usage :
la barre de recherche retrouve une note instantanément et hors ligne, l'agent
répond à une question au prix d'un appel au modèle.

## Stack

- **Backend** : FastAPI + SQLite, embeddings via `fastembed`
  (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`)
- **Frontend** : React + Vite
- **Agent** : LangGraph + Gemini, exposé en SSE par l'API et via Chainlit

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
# Tout : API, frontend et agent (http://localhost:8300)
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8300 --reload

# Optionnel — la même interface, en autonome (http://localhost:8400)
# À lancer depuis la racine du projet : Chainlit lit `chainlit.md` et
# `.chainlit/` dans le répertoire courant.
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
| `GET`    | `/api/conversations`      | Liste les conversations archivées   |
| `GET`    | `/api/conversations/{id}` | Dump complet d'une archive          |
| `DELETE` | `/api/conversations/{id}` | Supprime une archive                |
| —        | `/chat/`                  | Interface Chainlit montée           |

L'archivage n'a pas d'endpoint : il se déclenche depuis Chainlit, qui appelle
`journal.sauvegarder` directement. L'API ne fait que relire les archives, pour
l'onglet « Archives ».

## Agent

```
agent/
├── prompts.py   Prompt système, en blocs composables + son empreinte
├── tools.py     Les outils. Pour l'instant : rechercher_dans_les_notes
├── graph.py     Le graphe LangGraph, le budget et la config du modèle
├── journal.py   Archivage des conversations signalées
└── tracing.py   Traçage optionnel — seul fichier à toucher pour en changer

app.py           API + frontend, et monte Chainlit sur /chat (port 8300)
chainlit_app.py  L'interface de chat — la même aux deux points d'entrée
notes_store.py   Base, embeddings et recherche — partagés par les deux
```

Une seule implémentation du chat sert les deux surfaces : l'onglet « Agent »
affiche `/chat` dans une iframe, et `chainlit run` expose le même module sur
le port 8400. Ce qu'on déboguera sur 8400 est exactement ce que voit
l'utilisateur dans l'app.

> Le graphe est construit **à la demande** (`graphe()`), pas au démarrage :
> Starlette n'exécute pas le lifespan des sous-applications montées, donc
> `@cl.on_app_startup` ne se déclenche pas en mode monté. Une construction
> paresseuse, protégée par un verrou, marche dans les deux régimes.

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

## Analyser les mauvaises réponses

Deux niveaux, volontairement distincts.

### Le checkpointer — l'historique vivant

`conversations.db` porte l'état de chaque fil (`AsyncSqliteSaver`). Une
conversation survit au rechargement de la page et au redémarrage du serveur ;
l'agent se souvient du contexte d'une question à l'autre.

### Le journal — l'archive figée

Le bouton **« Signaler cette conversation »** (dans l'app comme dans Chainlit)
fige une copie *immuable* de l'échange, avec la configuration qui l'a
produite : modèle, budget de recherches, budget de réflexion, et l'empreinte
des prompts.

Cette empreinte est dérivée du texte des prompts, jamais tenue à la main —
impossible de retoucher un prompt en oubliant d'incrémenter un numéro. C'est
le point qui rend l'archive exploitable : relire dans six mois une mauvaise
réponse sans savoir quel prompt l'a produite ne sert à rien, et c'est
justement le prompt qu'on aura changé entre-temps.

Le dump conserve aussi les **résultats bruts de chaque recherche** (notes
remontées, scores, mots-clés absents), pas seulement le texte de la réponse :
c'est là que se lit *pourquoi* l'agent a mal répondu — mauvaise reformulation,
ou notes correctes mal exploitées. L'onglet **Archives** les liste et permet
de télécharger le JSON, de quoi constituer un jeu de test à partir des cas
ratés.

### Le traçage — optionnel, et éteint par défaut

**Tout ce qui précède fonctionne sans traçage.** `NOTES_AGENT_TRACING` est
vide par défaut : rien à installer, rien à faire tourner. Les paquets
correspondants ne sont même pas dans `requirements.txt`.

Activé, `agent/tracing.py` branche [Langfuse](https://langfuse.com)
auto-hébergé, qui capture ce que l'archive ne peut pas reconstruire : le
prompt système réellement envoyé, les tokens, la latence, les erreurs de
l'API. Le signalement y pousse en plus un score, ce qui rend la trace
retrouvable.

```bash
.venv/bin/pip install -r requirements-tracing.txt
# puis NOTES_AGENT_TRACING=langfuse et les clés dans .env
```

C'est un confort de débogage, pas une fonctionnalité. Le module dégrade en
silence à chaque étage : sans configuration il renvoie des valeurs neutres ;
configuré mais paquets absents, ou backend éteint, il avale l'erreur avec un
avertissement (une fois, pas à chaque appel) plutôt que de la remonter à
l'utilisateur — dont la question n'a pas à échouer parce qu'un conteneur est
arrêté. Le reste du code ignore qu'un backend existe : changer de
fournisseur, ou tout couper, ne touche que ce fichier.

> Langfuse v3 auto-hébergé n'est pas léger : six conteneurs (web, worker,
> PostgreSQL, ClickHouse, Redis, MinIO), et sa doc recommande 4 cœurs /
> 16 Gio pour une VM sous charge. C'est l'argument pour ne pas le monter tant
> que l'archivage local suffit — pas un prérequis de l'app.

### Faire évoluer

- **Nouvelle capacité** → un outil dans `agent/tools.py`, ajouté à `TOOLS`.
- **Nouvelle étape** (reranking, garde-fou, mémoire longue) → un nœud dans
  `agent/graph.py`.
- **Autre backend de traçage** (LangSmith, aucun) → `agent/tracing.py` seul.

### Variables d'environnement

| Variable                      | Défaut             | Rôle                                        |
| ----------------------------- | ------------------ | ------------------------------------------- |
| `GOOGLE_API_KEY`              | —                  | Requise par l'agent (`GEMINI_API_KEY` marche aussi) |
| `NOTES_AGENT_MODEL`           | `gemini-3.1-flash-lite` | Modèle utilisé                              |
| `NOTES_AGENT_MAX_RECHERCHES`  | `3`                | Recherches autorisées par question          |
| `NOTES_AGENT_THINKING_BUDGET` | défaut du modèle   | Budget de réflexion : `0` = désactivé, `-1` = dynamique |
| `NOTES_AGENT_TRACING`         | *(vide)*           | `langfuse` pour activer le traçage, vide pour l'éteindre |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | — | Requises si le traçage est actif |

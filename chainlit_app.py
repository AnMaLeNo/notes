"""Interface Chainlit de l'agent de recherche dans les notes.

Ce module sert les deux surfaces de chat, sans duplication :

- **monté dans l'app**, sur `/chat` du port 8300, affiché dans l'onglet
  « Agent » (voir `mount_chainlit` dans `app.py`) ;
- **autonome** sur le port 8400 :
  `.venv/bin/chainlit run chainlit_app.py -w --port 8400`.

Les deux partagent le graphe, le checkpointer et le journal : une
conversation signalée d'un côté apparaît dans les archives de l'autre.

Chaque appel d'outil est rendu comme un `cl.Step` dépliable : on y lit la
requête sémantique que l'agent a formulée et les notes qu'elle a ramenées.
"""

import asyncio
from pathlib import Path

import aiosqlite
import chainlit as cl
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Chainlit charge bien un `.env`, mais celui du répertoire *courant* : lancé
# depuis ailleurs, l'agent démarre sans clé. On vise donc le fichier du projet.
load_dotenv(Path(__file__).resolve().parent / ".env")

from agent import journal, tracing  # noqa: E402
from agent.graph import MODEL, build_graph, config_agent  # noqa: E402
from notes_store import get_model  # noqa: E402

_graph = None
_verrou = asyncio.Lock()


async def graphe():
    """Le graphe, construit au premier besoin.

    Initialisation paresseuse et non au démarrage, parce que ce module tourne
    sous deux régimes : en application Chainlit autonome (port 8400), où
    `on_app_startup` se déclenche ; et monté dans FastAPI (`/chat` du port
    8300), où il ne se déclenche **pas** — Starlette n'exécute pas le
    lifespan des sous-applications montées. Un graphe construit à la demande
    marche dans les deux cas.
    """
    global _graph
    if _graph is None:
        async with _verrou:
            if _graph is None:  # un autre appel a pu gagner la course
                journal.init_db()
                connexion = await aiosqlite.connect(journal.CONVERSATIONS_DB)
                checkpointer = AsyncSqliteSaver(connexion)
                await checkpointer.setup()
                _graph = build_graph(checkpointer)
    return _graph


@cl.on_app_startup
async def demarrer_app():
    """Préchauffe ce qui est lent, quand Chainlit tourne en autonome."""
    await graphe()
    # Le modèle d'embedding met quelques secondes à charger : on paie
    # l'attente ici plutôt qu'à la première question.
    await asyncio.to_thread(get_model)


@cl.set_starters
async def starters():
    return [
        cl.Starter(
            label="Mes projets en cours",
            message="Qu'est-ce que j'avais prévu de faire avec le Raspberry Pi ?",
        ),
        cl.Starter(
            label="Retrouver une idée",
            message="J'avais noté une idée autour de Claude et des workflows, c'était quoi ?",
        ),
        cl.Starter(
            label="Ce que j'ai à acheter",
            message="Est-ce que j'ai noté des trucs à acheter ?",
        ),
    ]


@cl.on_chat_start
async def demarrer():
    cl.user_session.set("thread_id", cl.context.session.id)


@cl.on_message
async def repondre(message: cl.Message):
    thread_id = cl.user_session.get("thread_id")
    trace_id = tracing.nouvelle_trace()
    cl.user_session.set("trace_id", trace_id)

    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": tracing.callbacks(trace_id),
        "metadata": {"modele": MODEL, "surface": "chainlit"},
    }
    reponse = cl.Message(content="")
    etapes: dict[str, cl.Step] = {}

    try:
        stream = (await graphe()).astream(
            # `recherches: 0` remet le budget à neuf à chaque question.
            {"messages": [HumanMessage(message.content)], "recherches": 0},
            config=config,
            stream_mode=["messages", "updates"],
        )
        async for mode, payload in stream:
            if mode == "messages":
                chunk, meta = payload
                if meta.get("langgraph_node") == "agent" and chunk.text:
                    await reponse.stream_token(chunk.text)
            elif mode == "updates":
                await _afficher_etapes(payload, etapes)
    except Exception as erreur:  # quota, réseau, modèle inconnu…
        # On referme les étapes en cours plutôt que de les supprimer : elles
        # disent où la requête s'est arrêtée.
        for etape in etapes.values():
            etape.output = "interrompu"
            await etape.update()
        await cl.ErrorMessage(content=f"{type(erreur).__name__} : {erreur}").send()
        # Une réponse qui plante est précisément celle qu'on veut archiver.
        await _proposer_sauvegarde()
        return

    reponse.actions = [
        cl.Action(
            name="sauvegarder",
            payload={"thread_id": thread_id, "trace_id": trace_id},
            label="Signaler cette réponse",
            tooltip="Archive la conversation et sa config pour analyse ultérieure",
        )
    ]
    await reponse.send()


async def _proposer_sauvegarde() -> None:
    await cl.Message(
        content="Cette conversation peut être archivée pour analyse.",
        actions=[
            cl.Action(
                name="sauvegarder",
                payload={
                    "thread_id": cl.user_session.get("thread_id"),
                    "trace_id": cl.user_session.get("trace_id"),
                },
                label="Signaler cette conversation",
            )
        ],
    ).send()


@cl.action_callback("sauvegarder")
async def sauvegarder(action: cl.Action):
    """Fige la conversation, avec le prompt et le modèle qui l'ont produite."""
    reponse = await cl.AskUserMessage(
        content="Qu'est-ce qui cloche dans cette réponse ? (facultatif — « ok » pour archiver tel quel)",
        timeout=120,
    ).send()
    motif = (reponse or {}).get("output", "").strip()
    if motif.lower() in {"ok", "rien", ""}:
        motif = ""

    thread_id = action.payload["thread_id"]
    etat = await (await graphe()).aget_state({"configurable": {"thread_id": thread_id}})
    messages = etat.values.get("messages", []) if etat else []
    if not messages:
        await cl.ErrorMessage(content="Conversation introuvable.").send()
        return

    tracing.signaler(action.payload.get("trace_id"), motif)
    enregistrement = journal.sauvegarder(
        thread_id=thread_id,
        messages=messages,
        config=config_agent(),
        motif=motif,
        origine="chainlit",
        trace_id=action.payload.get("trace_id"),
    )
    await cl.Message(
        content=(
            f"Conversation archivée (#{enregistrement['id']}, "
            f"prompt `{enregistrement['config']['version_prompt']}`, "
            f"modèle `{enregistrement['config']['modele']}`). "
            "Retrouvable dans l'onglet « Archives » de l'app."
        )
    ).send()


async def _afficher_etapes(payload: dict, etapes: dict[str, cl.Step]) -> None:
    """Ouvre un Step par appel d'outil, puis le referme avec son résultat."""
    for node, update in payload.items():
        if not isinstance(update, dict):
            continue
        for msg in update.get("messages", []):
            if node == "agent":
                for appel in getattr(msg, "tool_calls", None) or []:
                    args = appel["args"]
                    mots = ", ".join(args.get("mots_cles") or []) or "aucun"
                    etape = cl.Step(name="recherche", type="tool")
                    etape.input = f"sens : {args.get('requete', '')}\nmots-clés : {mots}"
                    await etape.send()
                    etapes[appel["id"]] = etape
            elif node == "recherches":
                etape = etapes.pop(getattr(msg, "tool_call_id", None), None)
                if etape is not None:
                    etape.output = msg.content
                    await etape.update()

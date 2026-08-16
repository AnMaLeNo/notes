"""Interface Chainlit de l'agent de recherche dans les notes.

Lancement : .venv/bin/chainlit run chainlit_app.py -w --port 8400

Chaque appel d'outil est rendu comme un `cl.Step` dépliable : on y lit la
requête sémantique que l'agent a formulée et les notes qu'elle a ramenées.
"""

import asyncio

import chainlit as cl
from langchain_core.messages import HumanMessage

from agent.graph import MODEL, build_graph
from notes_store import get_model

graph = build_graph()


@cl.on_app_startup
async def precharger_le_modele():
    """Charge les embeddings au démarrage pour que la 1re question ne traîne pas."""
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
    config = {
        "configurable": {"thread_id": cl.user_session.get("thread_id")},
        "metadata": {"modele": MODEL},
    }
    reponse = cl.Message(content="")
    etapes: dict[str, cl.Step] = {}

    try:
        stream = graph.astream(
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
        return

    await reponse.send()


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

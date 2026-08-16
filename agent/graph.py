"""Graphe LangGraph de l'agent.

Boucle minimale et volontairement explicite :

    START → agent ──(veut chercher ?)──→ recherches ──┐
              ↑                                       │
              └───────────────────────────────────────┘
              └──(non)──→ END

L'agent peut relancer une recherche tant qu'il juge les résultats
insuffisants, dans la limite de `MAX_RECHERCHES` par question. La limite est
tenue par le graphe, pas par le prompt : au-delà, le modèle est appelé *sans
outil*, donc il ne peut que répondre. Une consigne dans le prompt se négocie,
pas un outil absent.

Ajouter une capacité = ajouter un outil dans `agent/tools.py`. Ajouter une
étape (reranking, mémoire, garde-fou…) = ajouter un nœud ici.
"""

import os
from datetime import date

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent.prompts import PROMPT_SANS_RECHERCHE, SYSTEM_PROMPT
from agent.tools import TOOLS

MODEL = os.getenv("NOTES_AGENT_MODEL", "gemini-3.1-flash-lite")
MAX_OUTPUT_TOKENS = 4096

# Recherches autorisées par question. Assez pour deux reformulations après un
# premier essai raté, assez peu pour que l'utilisateur n'attende pas.
MAX_RECHERCHES = int(os.getenv("NOTES_AGENT_MAX_RECHERCHES", "3"))

# Budget de réflexion (tokens) : 0 le désactive, -1 le laisse dynamique.
# Non renseigné → on laisse le défaut du modèle.
_THINKING_BUDGET = os.getenv("NOTES_AGENT_THINKING_BUDGET")

# Sans outil, le modèle subit une forte pression à répondre quand même — et
# comble alors le vide en inventant une note. L'interdiction doit être plus
# ferme ici que dans le prompt général.
_EPUISE = (
    "Tu as utilisé tes {max} recherches pour cette question et tu ne peux plus "
    "en lancer. Réponds UNIQUEMENT à partir des résultats de recherche présents "
    "dans cette conversation. Si aucun ne contient l'information demandée, dis "
    "simplement que tu ne l'as pas trouvée dans les notes. N'invente aucune "
    "note, ne devine pas, ne complète pas avec tes connaissances générales : "
    "une réponse inventée est bien pire qu'un « je n'ai pas trouvé »."
)


class EtatAgent(MessagesState):
    """L'historique de conversation, plus le compteur de recherches du tour."""

    recherches: int


def api_key() -> str:
    cle = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not cle:
        raise RuntimeError(
            "Clé d'API manquante : renseigne GOOGLE_API_KEY (ou GEMINI_API_KEY) "
            "dans le fichier .env — voir .env.example."
        )
    return cle


def build_llm() -> ChatGoogleGenerativeAI:
    """Le modèle. Température basse : on veut une reformulation stable, pas créative."""
    options = {}
    if _THINKING_BUDGET is not None:
        options["thinking_budget"] = int(_THINKING_BUDGET)
    return ChatGoogleGenerativeAI(
        model=MODEL,
        google_api_key=api_key(),
        temperature=0.2,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        **options,
    )


def build_graph(checkpointer=None):
    """Compile le graphe. Le checkpointer porte l'historique de conversation."""
    llm = build_llm()
    llm_chercheur = llm.bind_tools(TOOLS)
    # Budget épuisé : l'outil reste déclaré mais l'API en interdit l'appel.
    # Le retirer purement et simplement ne marche pas — le prompt le décrit
    # encore, le modèle tente quand même l'appel et Gemini répond
    # MALFORMED_FUNCTION_CALL, c'est-à-dire une réponse vide.
    llm_muet = llm.bind_tools(TOOLS, tool_choice="none")
    outils = ToolNode(TOOLS)

    async def agent(state: EtatAgent):
        faites = state.get("recherches", 0)
        epuise = faites >= MAX_RECHERCHES

        base = PROMPT_SANS_RECHERCHE if epuise else SYSTEM_PROMPT
        # La date du jour permet de résoudre « hier », « cette semaine »…
        consigne = f"{base}\n\nDate du jour : {date.today():%d/%m/%Y}."
        if epuise:
            consigne += "\n\n" + _EPUISE.format(max=MAX_RECHERCHES)

        modele = llm_muet if epuise else llm_chercheur
        reponse = await modele.ainvoke([SystemMessage(consigne), *state["messages"]])
        return {"messages": [reponse]}

    async def recherches(state: EtatAgent):
        """Exécute les recherches et rappelle à l'agent où il en est de son budget."""
        resultat = await outils.ainvoke(state)
        faites = state.get("recherches", 0)
        messages = [
            msg.model_copy(
                update={
                    "content": f"{msg.content}\n\n"
                    f"(recherche {faites + i}/{MAX_RECHERCHES})"
                }
            )
            for i, msg in enumerate(resultat["messages"], start=1)
        ]
        return {"messages": messages, "recherches": faites + len(messages)}

    builder = StateGraph(EtatAgent)
    builder.add_node("agent", agent)
    builder.add_node("recherches", recherches)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent", tools_condition, {"tools": "recherches", END: END}
    )
    builder.add_edge("recherches", "agent")

    return builder.compile(checkpointer=checkpointer or InMemorySaver())

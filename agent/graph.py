"""Graphe LangGraph de l'agent.

Boucle minimale et volontairement explicite :

    START → agent ──(veut un outil ?)──→ outils ──┐
              ↑                                   │
              └───────────────────────────────────┘
              └──(non)──→ END

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

from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS

MODEL = os.getenv("NOTES_AGENT_MODEL", "gemini-3.1-flash-lite")
MAX_OUTPUT_TOKENS = 4096

# Budget de réflexion (tokens) : 0 le désactive, -1 le laisse dynamique.
# Non renseigné → on laisse le défaut du modèle.
_THINKING_BUDGET = os.getenv("NOTES_AGENT_THINKING_BUDGET")


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
    llm = build_llm().bind_tools(TOOLS)

    async def agent(state: MessagesState):
        # La date du jour permet de résoudre « hier », « cette semaine »…
        contexte = SystemMessage(
            f"{SYSTEM_PROMPT}\n\nDate du jour : {date.today():%d/%m/%Y}."
        )
        return {"messages": [await llm.ainvoke([contexte, *state["messages"]])]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent)
    builder.add_node("outils", ToolNode(TOOLS))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition, {"tools": "outils", END: END})
    builder.add_edge("outils", "agent")

    return builder.compile(checkpointer=checkpointer or InMemorySaver())

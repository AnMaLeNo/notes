"""Outils de l'agent.

Pour l'instant un seul : la recherche sémantique. Les suivants s'ajoutent ici
puis dans `TOOLS`, sans toucher au graphe.
"""

from datetime import datetime

from langchain_core.tools import tool

from notes_store import SCORE_THRESHOLD, search_notes

AGENT_SEARCH_LIMIT = 8


def _format_date(iso: str) -> str:
    """« 2026-08-15 21:02:11 » → « 15/08/2026 »."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


@tool(parse_docstring=True)
def rechercher_dans_les_notes(requete: str) -> str:
    """Recherche sémantique dans les notes personnelles de l'utilisateur.

    Appelle cet outil dès que la réponse dépend de ce que l'utilisateur a noté :
    c'est ton seul accès à ses notes. La recherche se fait par le sens, pas par
    mots-clés, donc les synonymes et les reformulations fonctionnent.

    Args:
        requete: Phrase affirmative décrivant la note recherchée, rédigée comme
            si tu écrivais toi-même cette note, l'information manquante notée X.
            Jamais une question, jamais une liste de mots-clés.
            OUI  : « la pizza 4 fromages d'Intermarché cuit X minutes à Y degrés »
            NON  : « combien de temps cuit la pizza 4 fromages ? »
            NON  : « temps de cuisson pizza 4 fromages Intermarché »
    """
    resultats = search_notes(requete, limit=AGENT_SEARCH_LIMIT)
    if not resultats:
        return (
            f"Aucune note au-dessus du seuil de similarité ({SCORE_THRESHOLD}). "
            "Reformule nettement différemment, ou conclus que l'information "
            "n'est pas dans les notes."
        )

    blocs = [
        f"[note {n['id']} · {_format_date(n['created_at'])} · similarité {n['score']}]\n"
        f"{n['content']}"
        for n in resultats
    ]
    entete = f"{len(resultats)} note(s), de la plus proche à la plus lointaine :"
    return "\n\n".join([entete, *blocs])


TOOLS = [rechercher_dans_les_notes]

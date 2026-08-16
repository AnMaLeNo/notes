"""Outils de l'agent.

Pour l'instant un seul : la recherche hybride. Les suivants s'ajoutent ici
puis dans `TOOLS`, sans toucher au graphe.

La recherche renvoie un couple `(texte, artefact)` : le texte part au modèle,
l'artefact reste attaché au `ToolMessage` sans consommer de tokens. C'est lui
qui permet à l'interface d'afficher les notes trouvées comme de vraies cartes
cliquables — et non comme le pavé de texte destiné au modèle — et de figurer
telles quelles dans les conversations sauvegardées.
"""

from datetime import datetime

from langchain_core.tools import tool

from notes_store import SCORE_THRESHOLD, search_hybrid

AGENT_SEARCH_LIMIT = 8


def _format_date(iso: str) -> str:
    """« 2026-08-15 21:02:11 » → « 15/08/2026 »."""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


@tool(parse_docstring=True, response_format="content_and_artifact")
def rechercher_dans_les_notes(requete: str, mots_cles: list[str]) -> tuple[str, dict]:
    """Recherche dans les notes personnelles de l'utilisateur.

    Appelle cet outil dès que la réponse dépend de ce que l'utilisateur a noté :
    c'est ton seul accès à ses notes. Deux recherches tournent en parallèle et
    leurs classements sont fusionnés — le sens via `requete`, les termes exacts
    via `mots_cles`. Renseigne toujours les deux : le sens rattrape les
    synonymes et les fautes de frappe, les mots-clés ancrent la recherche sur
    les termes qui ne peuvent pas être devinés.

    Args:
        requete: Phrase affirmative décrivant la note recherchée, rédigée comme
            si tu écrivais toi-même cette note, l'information manquante notée X.
            Jamais une question, jamais une liste de mots-clés.
            OUI  : « la pizza 4 fromages d'Intermarché cuit X minutes à Y degrés »
            NON  : « combien de temps cuit la pizza 4 fromages ? »
            NON  : « temps de cuisson pizza 4 fromages Intermarché »
        mots_cles: Termes distinctifs de la demande, ceux qui doivent
            littéralement figurer dans la note : noms propres, marques,
            technologies, chiffres. Pour la pizza : ["pizza", "4 fromages",
            "Intermarché"]. Pas de mots vides ni de verbes génériques
            ("faire", "temps", "chose"). Liste vide si la demande n'en
            contient aucun.
    """
    resultat = search_hybrid(requete, mots_cles, limit=AGENT_SEARCH_LIMIT)
    notes, absents = resultat["notes"], resultat["mots_cles_absents"]

    alertes = []
    if absents:
        alertes.append(
            "Introuvables dans TOUTE la base : "
            + ", ".join(f"« {m} »" for m in absents)
            + "."
        )

    if not notes:
        texte = "\n".join(
            [
                f"Aucun résultat : aucune note au-dessus du seuil de similarité "
                f"({SCORE_THRESHOLD}) et aucun mot-clé trouvé.",
                *alertes,
            ]
        )
        return texte, resultat

    blocs = []
    for n in notes:
        trouves = ", ".join(n["mots_cles"]) if n["mots_cles"] else "aucun"
        blocs.append(
            f"[note {n['id']} · {_format_date(n['created_at'])} · "
            f"sémantique {n['score']} · mots-clés : {trouves}]\n{n['content']}"
        )

    entete = [f"{len(notes)} note(s), classement fusionné sens + mots-clés :", *alertes]
    return "\n\n".join(["\n".join(entete), *blocs]), resultat


TOOLS = [rechercher_dans_les_notes]

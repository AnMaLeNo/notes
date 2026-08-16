"""Traçage optionnel de l'agent — une seule porte d'entrée.

Le traçage n'est *jamais* nécessaire pour que l'agent tourne. Sans
configuration, chaque fonction de ce module renvoie une valeur neutre et le
reste du code ignore qu'un backend existe. C'est délibéré : le jour où
Langfuse te fatigue (six conteneurs pour une app de notes), ce fichier est le
seul à changer — passer à LangSmith ou tout couper ne touche ni le graphe, ni
l'API, ni le frontend.

Activation : `NOTES_AGENT_TRACING=langfuse` dans `.env`, plus les clés
Langfuse. Voir `.env.example`.

Le traçage est un confort de débogage, pas une fonctionnalité : toute panne
côté backend est avalée avec un avertissement plutôt que remontée à
l'utilisateur, qui n'a pas à voir sa question échouer parce qu'un conteneur
est éteint.
"""

import os
import sys

BACKEND = os.getenv("NOTES_AGENT_TRACING", "").strip().lower()
ACTIF = BACKEND == "langfuse"

_client = None
_avertissements: set[str] = set()


def _avertir(message: str) -> None:
    """Une fois par message : un traçage cassé ne doit pas noyer les logs."""
    if message not in _avertissements:
        _avertissements.add(message)
        print(f"[tracing] {message}", file=sys.stderr)


def _langfuse():
    global _client
    if _client is None:
        from langfuse import get_client

        _client = get_client()
    return _client


def nouvelle_trace() -> str | None:
    """Identifiant de trace, généré *avant* d'appeler le graphe.

    On le génère soi-même plutôt que de le récupérer après coup : le frontend
    le reçoit dès l'ouverture du flux, donc même une conversation qui plante
    en cours de route reste rattachable à sa trace. C'est lui qui relie la
    conversation sauvegardée localement à son détail complet côté Langfuse.
    """
    if not ACTIF:
        return None
    try:
        from langfuse import Langfuse

        return Langfuse.create_trace_id()
    except Exception as erreur:  # paquet absent, clés manquantes…
        _avertir(f"trace non créée ({type(erreur).__name__}: {erreur})")
        return None


def callbacks(trace_id: str | None) -> list:
    """Callbacks à passer dans le `config` de LangGraph. Vide si inactif."""
    if not ACTIF or trace_id is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler(trace_context={"trace_id": trace_id})]
    except Exception as erreur:
        _avertir(f"handler indisponible ({type(erreur).__name__}: {erreur})")
        return []


def signaler(trace_id: str | None, commentaire: str = "") -> None:
    """Marque la trace comme mauvaise côté backend.

    Pendant du bouton « signaler » : la sauvegarde locale garde la
    conversation, ce score-ci rend la trace correspondante retrouvable dans
    Langfuse et convertible en cas de test.
    """
    if not ACTIF or not trace_id:
        return
    try:
        client = _langfuse()
        client.create_score(
            trace_id=trace_id,
            name="signalement",
            value=0,
            data_type="NUMERIC",
            comment=commentaire or "signalé depuis l'app",
        )
        # L'envoi est asynchrone et bufferisé : sans flush, un score posté
        # juste avant l'arrêt du serveur se perd.
        client.flush()
    except Exception as erreur:
        _avertir(f"signalement non transmis ({type(erreur).__name__}: {erreur})")

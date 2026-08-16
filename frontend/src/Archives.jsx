import { useCallback, useEffect, useState } from 'react'

function formatDate(iso) {
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Un échange du dump : question, recherches lancées, résultats, réponse. */
function Echange({ echange }) {
  if (echange.role === 'utilisateur') {
    return <p className="bulle bulle-user">{echange.contenu}</p>
  }

  if (echange.role === 'outil') {
    const notes = echange.resultats?.notes || []
    const absents = echange.resultats?.mots_cles_absents || []
    return (
      <div className="archive-outil">
        <p className="etape-champ">
          <span className="etape-label">
            recherche {echange.resultats?.recherche}/
            {echange.resultats?.max_recherches}
          </span>{' '}
          {notes.length} note(s)
        </p>
        {absents.length > 0 && (
          <p className="etape-champ etape-absent">
            <span className="etape-label">introuvables</span> {absents.join(', ')}
          </p>
        )}
        {notes.map((note) => (
          <article key={note.id} className="source">
            <p className="note-content">{note.content}</p>
            <footer className="note-meta">
              <span className="note-score">
                {Math.round(note.score * 100)} %
              </span>
              {note.mots_cles?.length > 0 && (
                <span className="source-mots">{note.mots_cles.join(' · ')}</span>
              )}
            </footer>
          </article>
        ))}
      </div>
    )
  }

  return (
    <div className="bulle bulle-agent">
      {echange.recherches_demandees?.map((appel, i) => (
        <p key={i} className="etape-champ">
          <span className="etape-label">cherche</span> {appel.args.requete}
          {appel.args.mots_cles?.length > 0 && (
            <> · {appel.args.mots_cles.join(', ')}</>
          )}
        </p>
      ))}
      {echange.contenu && <p className="agent-texte">{echange.contenu}</p>}
    </div>
  )
}

export default function Archives() {
  const [conversations, setConversations] = useState([])
  const [ouverte, setOuverte] = useState(null)
  const [erreur, setErreur] = useState(null)

  const charger = useCallback(async () => {
    try {
      const res = await fetch('/api/conversations')
      if (!res.ok) throw new Error()
      setConversations(await res.json())
    } catch {
      setErreur('Impossible de charger les archives')
    }
  }, [])

  // Le composant est monté à chaque passage sur l'onglet : une conversation
  // signalée depuis l'iframe apparaît donc dès qu'on revient ici.
  useEffect(() => {
    charger()
  }, [charger])

  async function ouvrir(id) {
    if (ouverte?.id === id) return setOuverte(null)
    try {
      const res = await fetch(`/api/conversations/${id}`)
      if (!res.ok) throw new Error()
      setOuverte(await res.json())
    } catch {
      setErreur('Impossible de lire cette conversation')
    }
  }

  async function supprimer(id) {
    try {
      await fetch(`/api/conversations/${id}`, { method: 'DELETE' })
      if (ouverte?.id === id) setOuverte(null)
      await charger()
    } catch {
      setErreur('Suppression impossible')
    }
  }

  function telecharger(conversation) {
    // Un fichier JSON, pour analyser hors de l'app — ou constituer un jeu de
    // test à partir des cas ratés.
    const blob = new Blob([JSON.stringify(conversation, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const lien = document.createElement('a')
    lien.href = url
    lien.download = `conversation-${conversation.id}.json`
    lien.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section className="notes">
      {erreur && <p className="error">{erreur}</p>}

      <h2 className="notes-heading">
        {conversations.length} conversation
        {conversations.length > 1 ? 's' : ''} archivée
        {conversations.length > 1 ? 's' : ''}
      </h2>

      {conversations.length === 0 && (
        <p className="empty">
          Rien d'archivé. Depuis l'onglet Agent, « Signaler cette conversation »
          fige un échange raté avec le modèle et le prompt qui l'ont produit.
        </p>
      )}

      {conversations.map((conversation) => (
        <article key={conversation.id} className="note-card">
          <button
            className="archive-tete"
            onClick={() => ouvrir(conversation.id)}
          >
            <span className="archive-question">
              {conversation.question || '(sans question)'}
            </span>
          </button>

          {conversation.motif && (
            <p className="archive-motif">« {conversation.motif} »</p>
          )}

          <footer className="note-meta archive-meta">
            <time>{formatDate(conversation.cree_le)}</time>
            <span className="archive-tag">{conversation.config.modele}</span>
            <span className="archive-tag">
              prompt {conversation.config.version_prompt}
            </span>
            <span className="archive-tag">{conversation.origine}</span>
            {conversation.trace_id && (
              <span className="archive-tag" title={conversation.trace_id}>
                tracé
              </span>
            )}
            <button
              className="note-delete"
              title="Supprimer l'archive"
              onClick={() => supprimer(conversation.id)}
            >
              ✕
            </button>
          </footer>

          {ouverte?.id === conversation.id && (
            <div className="archive-detail">
              {ouverte.echanges.map((echange, i) => (
                <Echange key={i} echange={echange} />
              ))}
              <button className="btn" onClick={() => telecharger(ouverte)}>
                Télécharger le JSON
              </button>
            </div>
          )}
        </article>
      ))}
    </section>
  )
}

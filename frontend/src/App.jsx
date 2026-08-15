import { useCallback, useEffect, useRef, useState } from 'react'
import Map2D from './Map2D.jsx'
import Map3D from './Map3D.jsx'

async function api(path, options) {
  const res = await fetch(path, options)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function formatDate(iso) {
  return new Date(iso.replace(' ', 'T')).toLocaleString('fr-FR', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const VIEWS = [
  { id: 'list', label: 'Liste' },
  { id: '2d', label: 'Carte 2D' },
  { id: '3d', label: 'Carte 3D' },
]

function initialView() {
  const h = window.location.hash.replace('#', '')
  return VIEWS.some((v) => v.id === h) ? h : 'list'
}

function NoteCard({ note, onDelete }) {
  return (
    <article className="note-card">
      <p className="note-content">{note.content}</p>
      <footer className="note-meta">
        <time>{formatDate(note.created_at)}</time>
        {note.score !== undefined && (
          <span className="note-score">{Math.round(note.score * 100)} %</span>
        )}
        <button
          className="note-delete"
          title="Supprimer"
          onClick={() => onDelete(note)}
        >
          ✕
        </button>
      </footer>
    </article>
  )
}

/** Dialogue natif : le navigateur gère le piégeage du focus et la touche Échap. */
function ConfirmDelete({ note, busy, onCancel, onConfirm }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    dialogRef.current?.showModal()
  }, [])

  return (
    <dialog
      className="confirm"
      ref={dialogRef}
      onCancel={(e) => {
        if (busy) e.preventDefault()
      }}
      onClose={onCancel}
      onClick={(e) => {
        if (e.target === dialogRef.current) onCancel()
      }}
    >
      <div className="confirm-body">
        <h2 className="confirm-title">Supprimer cette note ?</h2>
        <p className="confirm-preview">{note.content}</p>
        <p className="confirm-warning">Cette action est définitive.</p>
        <div className="confirm-actions">
          <button className="btn" onClick={onCancel} disabled={busy} autoFocus>
            Annuler
          </button>
          <button className="btn btn-danger" onClick={onConfirm} disabled={busy}>
            {busy ? 'Suppression…' : 'Supprimer'}
          </button>
        </div>
      </div>
    </dialog>
  )
}

export default function App() {
  const [view, setView] = useState(initialView)
  const [notes, setNotes] = useState([])
  const [results, setResults] = useState(null)
  const [mapData, setMapData] = useState([])
  const [hovered, setHovered] = useState(null)
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState(null)
  const [notesVersion, setNotesVersion] = useState(0)
  const debounceRef = useRef(null)

  const refresh = useCallback(async () => {
    setNotes(await api('/api/notes'))
    setNotesVersion((v) => v + 1)
  }, [])

  useEffect(() => {
    refresh().catch(() => setError('Impossible de charger les notes'))
  }, [refresh])

  useEffect(() => {
    history.replaceState(null, '', view === 'list' ? window.location.pathname : `#${view}`)
  }, [view])

  useEffect(() => {
    if (view === 'list') return
    let active = true
    const load = () =>
      api('/api/map')
        .then((d) => active && setMapData(d))
        .catch(() => {})
    load()
    const timer = setInterval(load, 10000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [view, notesVersion])

  useEffect(() => {
    clearTimeout(debounceRef.current)
    const q = query.trim()
    if (!q) {
      setResults(null)
      return
    }
    debounceRef.current = setTimeout(async () => {
      try {
        setResults(await api(`/api/search?q=${encodeURIComponent(q)}`))
      } catch {
        setError('Recherche impossible')
      }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query])

  async function saveDraft() {
    const content = draft.trim()
    if (!content || saving) return
    setSaving(true)
    setError(null)
    try {
      await api('/api/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      setDraft('')
      await refresh()
    } catch {
      setError("La note n'a pas pu être enregistrée")
    } finally {
      setSaving(false)
    }
  }

  async function confirmDelete() {
    const note = pendingDelete
    if (!note || deleting) return
    setDeleting(true)
    setError(null)
    try {
      await api(`/api/notes/${note.id}`, { method: 'DELETE' })
      setPendingDelete(null)
      await refresh()
      setResults((prev) => (prev ? prev.filter((n) => n.id !== note.id) : prev))
    } catch {
      setError('Suppression impossible')
      setPendingDelete(null)
    } finally {
      setDeleting(false)
    }
  }

  function cancelDelete() {
    if (!deleting) setPendingDelete(null)
  }

  function onDraftKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      saveDraft()
    }
  }

  function switchView(id) {
    setHovered(null)
    setView(id)
  }

  const searching = results !== null
  const shown = searching ? results : notes

  return (
    <main className="app">
      <header className="app-header">
        <h1>Notes</h1>
        {view === 'list' && (
          <input
            className="search-input"
            type="search"
            placeholder="Recherche sémantique…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}
      </header>

      <nav className="tabs">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            className={view === v.id ? 'tab active' : 'tab'}
            onClick={() => switchView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </nav>

      {error && <p className="error">{error}</p>}

      {view === 'list' ? (
        <>
          <section className="composer">
            <textarea
              className="composer-input"
              placeholder="Écris ta note, puis Entrée pour l'enregistrer (Maj+Entrée : nouvelle ligne)"
              value={draft}
              rows={3}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onDraftKeyDown}
              disabled={saving}
            />
          </section>

          <section className="notes">
            <h2 className="notes-heading">
              {searching
                ? `${shown.length} résultat${shown.length > 1 ? 's' : ''}`
                : `${shown.length} note${shown.length > 1 ? 's' : ''}`}
            </h2>
            {shown.length === 0 && (
              <p className="empty">
                {searching ? 'Aucune note ne correspond.' : 'Aucune note pour le moment.'}
              </p>
            )}
            {shown.map((note) => (
              <NoteCard key={note.id} note={note} onDelete={setPendingDelete} />
            ))}
          </section>
        </>
      ) : (
        <section className="map-section">
          {mapData.length < 2 ? (
            <p className="empty">Il faut au moins 2 notes pour afficher la carte.</p>
          ) : view === '2d' ? (
            <Map2D notes={mapData} hovered={hovered} onHover={setHovered} />
          ) : (
            <Map3D notes={mapData} hovered={hovered} onHover={setHovered} />
          )}
          <div className="map-tooltip">
            {hovered ? (
              <>
                <p className="note-content">{hovered.content}</p>
                <time className="note-meta">{formatDate(hovered.created_at)}</time>
              </>
            ) : (
              <p className="map-hint">
                {view === '3d'
                  ? 'Glisse pour faire pivoter · survole un point pour lire la note'
                  : 'Survole un point pour lire la note'}
              </p>
            )}
          </div>
        </section>
      )}

      {pendingDelete && (
        <ConfirmDelete
          note={pendingDelete}
          busy={deleting}
          onCancel={cancelDelete}
          onConfirm={confirmDelete}
        />
      )}
    </main>
  )
}

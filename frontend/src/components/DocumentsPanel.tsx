import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { FileText, FolderOpen, ShieldCheck, Trash2, Upload } from 'lucide-react'
import type { useDocuments } from '../hooks/useDocuments'
import type { IndexedDocument } from '../types'
import { Notice } from './Notice'

type DocumentsPanelProps = { catalog: ReturnType<typeof useDocuments> }

function DeleteConfirmation({ document, onCancel, onConfirm }: {
  document: IndexedDocument
  onCancel: () => void
  onConfirm: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const node = dialog.current
    node?.showModal()
    return () => node?.close()
  }, [])

  return (
    <dialog
      ref={dialog}
      className="confirmation-dialog"
      aria-labelledby="delete-title"
      aria-describedby="delete-description"
      onCancel={(event) => { event.preventDefault(); onCancel() }}
    >
      <h3 id="delete-title">Supprimer ce document ?</h3>
      <p id="delete-description">« {document.file} » sera retiré de la bibliothèque et de l’index.</p>
      <div className="confirmation-actions">
        <button type="button" className="secondary-button" autoFocus onClick={onCancel}>Annuler</button>
        <button type="button" className="danger-button" onClick={onConfirm}>Supprimer le PDF</button>
      </div>
    </dialog>
  )
}

function DocumentRow({ document, disabled, onDelete }: {
  document: IndexedDocument
  disabled: boolean
  onDelete: () => void
}) {
  const uploaded = document.origin === 'upload'
  const metadata = [document.type, document.date, document.version && `Version ${document.version}`, document.status]
    .filter(Boolean).join(' · ')

  return (
    <li className="document-row">
      <div className="document-icon"><FileText size={20} aria-hidden="true" /></div>
      <div className="document-details">
        <strong>{document.file}</strong>
        {document.reference && <small>{document.reference}</small>}
        {metadata && <small>{metadata}</small>}
      </div>
      <div className="document-stats">
        <span className={`document-origin ${uploaded ? 'document-origin--upload' : ''}`}>
          {uploaded ? <Upload size={13} aria-hidden="true" /> : <ShieldCheck size={13} aria-hidden="true" />}
          {uploaded ? 'Téléversé' : 'Officiel'}
        </span>
        <small>{document.page_count} {document.page_count === 1 ? 'page' : 'pages'} · {document.chunk_count} {document.chunk_count === 1 ? 'fragment' : 'fragments'}</small>
      </div>
      {uploaded && (
        <button
          type="button"
          className="danger-button document-delete"
          aria-label={`Supprimer ${document.file}`}
          disabled={disabled}
          onClick={onDelete}
        >
          <Trash2 size={16} aria-hidden="true" /> Supprimer
        </button>
      )}
    </li>
  )
}

export function DocumentsPanel({ catalog }: DocumentsPanelProps) {
  const { documents, loading, listError, pending, feedback, busy, refresh, upload, remove } = catalog
  const [file, setFile] = useState<File | null>(null)
  const [selectionError, setSelectionError] = useState<string | null>(null)
  const [confirmedDocument, setConfirmedDocument] = useState<IndexedDocument | null>(null)
  const input = useRef<HTMLInputElement>(null)

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.currentTarget.files?.[0] ?? null
    const invalid = selected !== null && !/\.pdf$/i.test(selected.name)
    setSelectionError(invalid ? 'Sélectionnez un fichier au format PDF.' : null)
    setFile(invalid ? null : selected)
    if (invalid) event.currentTarget.value = ''
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || busy) return
    if (await upload(file)) {
      setFile(null)
      if (input.current) input.current.value = ''
    }
  }

  function confirmDelete() {
    if (!confirmedDocument || busy) return
    setConfirmedDocument(null)
    void remove(confirmedDocument)
  }

  return (
    <>
      <div className="panel-heading">
        <div>
          <span className="panel-kicker"><FolderOpen size={15} aria-hidden="true" /> Bibliothèque</span>
          <h2>Documents indexés</h2>
          <p>Consultez le corpus officiel et ajoutez vos PDF à l’index.</p>
        </div>
        <div className="document-count" aria-label={`${documents.length} documents indexés`}>{documents.length}</div>
      </div>

      <div className="document-panel-content">
        <form className="document-upload" onSubmit={submit}>
          <label className="document-file-label">
            <span id="pdf-file-label">Fichier PDF</span>
            <input
              className="document-file-input"
              type="file"
              accept=".pdf,application/pdf"
              ref={input}
              disabled={busy}
              aria-labelledby="pdf-file-label"
              aria-invalid={selectionError ? true : undefined}
              aria-describedby={selectionError ? 'pdf-selection-error' : undefined}
              onChange={selectFile}
            />
            <span className="document-file-picker field-control" aria-hidden="true">
              <span>Choisir un PDF</span>
              <span>{file?.name ?? 'Aucun fichier'}</span>
            </span>
          </label>
          <button className="primary-button" type="submit" disabled={busy || !file}>
            <Upload size={16} aria-hidden="true" />
            {pending?.kind === 'upload' ? 'Téléversement…' : 'Téléverser le PDF'}
          </button>
        </form>

        <div className="document-notices">
          {selectionError && <Notice tone="error"><span id="pdf-selection-error">{selectionError}</span></Notice>}
          {pending && (
            <Notice tone="info" loading>
              {pending.kind === 'upload' ? 'Téléversement' : 'Suppression'} de « {pending.filename} » et mise à jour de l’index…
            </Notice>
          )}
          {!pending && loading && <Notice tone="info" loading>Chargement des documents…</Notice>}
          {listError && (
            <Notice tone="error">
              <p>Actualisation du catalogue impossible. {listError}</p>
              <button type="button" className="secondary-button" onClick={() => void refresh()} disabled={busy}>Réessayer</button>
            </Notice>
          )}
          {!pending && feedback && <Notice key={feedback.message} tone={feedback.tone}>{feedback.message}</Notice>}
        </div>

        <div aria-busy={busy}>
          {documents.length > 0 ? (
            <ul className="document-list" aria-label="Documents indexés">
              {documents.map((document) => (
                <DocumentRow
                  key={document.file}
                  document={document}
                  disabled={busy}
                  onDelete={() => setConfirmedDocument(document)}
                />
              ))}
            </ul>
          ) : !loading && !listError && (
            <div className="empty-state document-empty">
              <FolderOpen size={26} aria-hidden="true" />
              <strong>Aucun document indexé.</strong>
              <span>Téléversez un PDF pour alimenter la bibliothèque.</span>
            </div>
          )}
        </div>
      </div>

      {confirmedDocument && (
        <DeleteConfirmation
          document={confirmedDocument}
          onCancel={() => setConfirmedDocument(null)}
          onConfirm={confirmDelete}
        />
      )}
    </>
  )
}

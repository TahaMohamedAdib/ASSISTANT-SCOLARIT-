import { AlertCircle, CheckCircle2, Loader2, RotateCcw, UploadCloud, X } from 'lucide-react'
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { api, ApiError } from '../api/client'
import { useT, type StringKey } from '../i18n'
import { formatSize, useApp } from '../state'
import type { DocumentRow } from '../types'

export const PIPELINE = ['uploaded', 'parsing', 'chunking', 'embedding', 'indexed'] as const

type Item = {
  key: string
  file: File
  title: string
  doc_type: string
  department: string
  effective_date: string
  version: string
  official: boolean
  replaceId: string | null
  replaceTitle?: string
  state: 'draft' | 'uploading' | 'processing' | 'indexed' | 'review' | 'failed' | 'conflict'
  stage?: string
  progress?: number
  error?: string
  conflict?: { code: string; documentId?: string }
  jobId?: string | null
  documentId?: string
}

const stripExtension = (name: string) => name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim()

/** Televersement admin : depot multi-fichiers, metadonnees, pipeline en direct, doublons et versions. */
export function UploadPanel({ replaceTarget, onClose, onChanged }: { replaceTarget: DocumentRow | null; onClose: () => void; onChanged: () => void }) {
  const { t } = useT()
  const { settings } = useApp()
  const [items, setItems] = useState<Item[]>([])
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const types = settings?.doc_types ?? ['Autre']
  const extensions = settings?.allowed_extensions ?? ['.pdf']
  const maxMb = settings?.max_upload_mb ?? 20

  const update = (key: string, patch: Partial<Item>) => setItems((current) => current.map((i) => (i.key === key ? { ...i, ...patch } : i)))

  const add = (files: FileList | File[]) => {
    const next: Item[] = [...files].map((file) => {
      const ext = `.${file.name.split('.').pop()?.toLowerCase()}`
      const error = !extensions.includes(ext) ? t('upload.badType') : file.size > maxMb * 1024 * 1024 ? t('upload.tooBig', { max: maxMb }) : undefined
      return {
        key: `${file.name}-${file.size}-${Math.random()}`, file,
        title: replaceTarget?.title ?? stripExtension(file.name),
        doc_type: replaceTarget?.doc_type ?? (types.includes('Autre') ? 'Autre' : types[0]),
        department: replaceTarget?.department ?? '', effective_date: '', version: '', official: true,
        replaceId: replaceTarget?.id ?? null, replaceTitle: replaceTarget?.title,
        state: error ? 'failed' : 'draft', error,
      }
    })
    setItems((current) => (replaceTarget ? next.slice(0, 1) : [...current, ...next]))
  }

  // Suivi des taches d'indexation en cours
  useEffect(() => {
    const running = items.filter((i) => i.state === 'processing' && i.jobId)
    if (!running.length) return
    const timer = setInterval(async () => {
      for (const item of running) {
        try {
          const job = await api.job(item.jobId!)
          if (job.stage === 'indexed') {
            update(item.key, { state: 'indexed', stage: 'indexed', progress: 1 })
            onChanged()
          } else if (job.stage === 'failed') {
            update(item.key, { state: 'failed', stage: 'failed', error: job.error ?? t('errors.server') })
            onChanged()
          } else update(item.key, { stage: job.stage, progress: job.progress })
        } catch {
          // reessaye au prochain tour
        }
      }
    }, 700)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  const submit = async (item: Item, options: { replaceId?: string | null; allowSameTitle?: boolean } = {}) => {
    update(item.key, { state: 'uploading', stage: 'uploaded', progress: 0, error: undefined, conflict: undefined })
    try {
      const result = await api.upload(item.file, {
        title: item.title, doc_type: item.doc_type, department: item.department, effective_date: item.effective_date,
        version: item.version, official: item.official, replace_id: options.replaceId ?? item.replaceId ?? '',
        allow_same_title: options.allowSameTitle ?? false,
      })
      const review = result.document.status === 'pending_review'
      update(item.key, { state: review ? 'review' : 'processing', jobId: result.job_id, documentId: result.document.id })
      onChanged()
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'conflict') {
        update(item.key, { state: 'conflict', conflict: { code: error.code ?? '', documentId: error.documentId }, error: error.code === 'duplicate' ? t('upload.duplicate') : t('upload.titleExists') })
      } else {
        update(item.key, { state: 'failed', error: error instanceof ApiError && error.kind === 'rejected' ? error.message : error instanceof ApiError && error.kind === 'unauthorized' ? t('errors.unauthorized') : t('errors.server') })
      }
    }
  }

  const retry = async (item: Item) => {
    if (item.documentId && item.stage === 'failed') {
      update(item.key, { state: 'processing', stage: 'parsing', progress: 0, error: undefined })
      try {
        const { job_id } = await api.reindex(item.documentId)
        update(item.key, { jobId: job_id })
      } catch {
        update(item.key, { state: 'failed', error: t('errors.server') })
      }
    } else void submit(item)
  }

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setDragging(false)
    if (event.dataTransfer.files.length) add(event.dataTransfer.files)
  }
  const drafts = items.filter((i) => i.state === 'draft')

  return (
    <section className="upload-panel" aria-labelledby="upload-title">
      <header className="upload-panel__header">
        <h2 id="upload-title">{replaceTarget ? t('upload.replacing', { title: replaceTarget.title }) : t('upload.title')}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t('common.close')}><X size={18} /></button>
      </header>
      <div
        className={`dropzone${dragging ? ' dropzone--active' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <UploadCloud size={28} aria-hidden />
        <p>
          {t('upload.drop')}{' '}
          <button type="button" className="link-btn" onClick={() => input.current?.click()}>{t('upload.browse')}</button>
        </p>
        <p className="muted small">{t('upload.accepted', { types: extensions.join(' '), max: maxMb })}</p>
        <input ref={input} type="file" hidden multiple={!replaceTarget} accept={extensions.join(',')} data-testid="upload-input"
          onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = '' }} />
      </div>

      {items.length > 0 && (
        <ul className="upload-list">
          {items.map((item) => (
            <li key={item.key} className="upload-item">
              <div className="upload-item__head">
                <strong className="upload-item__name">{item.file.name}</strong>
                <span className="muted small">{formatSize(item.file.size)}</span>
                {item.state === 'draft' && <button type="button" className="icon-btn icon-btn--sm" onClick={() => setItems((c) => c.filter((i) => i.key !== item.key))} aria-label={t('upload.remove')}><X size={14} /></button>}
              </div>

              {item.state === 'draft' ? (
                <div className="upload-form">
                  <label className="field field--wide"><span className="field__label">{t('upload.fieldTitle')}</span>
                    <input value={item.title} onChange={(e) => update(item.key, { title: e.target.value })} maxLength={200} required />
                  </label>
                  <label className="field"><span className="field__label">{t('upload.fieldType')}</span>
                    <select value={item.doc_type} onChange={(e) => update(item.key, { doc_type: e.target.value })}>
                      {types.map((type) => <option key={type}>{type}</option>)}
                    </select>
                  </label>
                  <label className="field"><span className="field__label">{t('upload.fieldDepartment')}</span>
                    <input value={item.department} onChange={(e) => update(item.key, { department: e.target.value })} maxLength={120} />
                  </label>
                  <label className="field"><span className="field__label">{t('upload.fieldDate')}</span>
                    <input type="date" value={item.effective_date} onChange={(e) => update(item.key, { effective_date: e.target.value })} />
                  </label>
                  <label className="field"><span className="field__label">{t('upload.fieldVersion')}</span>
                    <input value={item.version} onChange={(e) => update(item.key, { version: e.target.value })} maxLength={40} placeholder="v1" />
                  </label>
                  <label className="switch"><input type="checkbox" checked={item.official} onChange={(e) => update(item.key, { official: e.target.checked })} /><span className="field__label">{t('upload.fieldOfficial')}</span></label>
                  {!replaceTarget || items.length === 1 ? (
                    <button type="button" className="btn btn--primary" disabled={!item.title.trim()} onClick={() => submit(item)}>{t('upload.submit')}</button>
                  ) : null}
                </div>
              ) : (
                <Pipeline item={item} />
              )}

              {item.state === 'conflict' && (
                <div className="inline-error" role="alert">
                  <span><AlertCircle size={16} aria-hidden /> {item.error}</span>
                  {item.conflict?.documentId && (
                    <button type="button" className="btn btn--secondary btn--sm" onClick={() => submit(item, { replaceId: item.conflict!.documentId })}>{t('upload.replaceAction')}</button>
                  )}
                  {item.conflict?.code === 'title_exists' && (
                    <button type="button" className="btn btn--ghost btn--sm" onClick={() => submit(item, { allowSameTitle: true })}>{t('upload.keepBoth')}</button>
                  )}
                </div>
              )}
              {item.state === 'failed' && (
                <div className="inline-error" role="alert">
                  <span><AlertCircle size={16} aria-hidden /> {item.error}</span>
                  {item.file.size <= maxMb * 1024 * 1024 && item.error !== t('upload.badType') && (
                    <button type="button" className="btn btn--secondary btn--sm" onClick={() => retry(item)}><RotateCcw size={14} aria-hidden /> {t('errors.retry')}</button>
                  )}
                </div>
              )}
              {item.state === 'indexed' && <p className="success-text" role="status"><CheckCircle2 size={16} aria-hidden /> {t('upload.done')}</p>}
              {item.state === 'review' && <p className="note" role="status">{t('upload.review')}</p>}
            </li>
          ))}
        </ul>
      )}
      {drafts.length > 1 && (
        <button type="button" className="btn btn--primary upload-panel__all" onClick={() => drafts.forEach((d) => d.title.trim() && submit(d))}>{t('upload.submitAll')} ({drafts.length})</button>
      )}
    </section>
  )
}

function Pipeline({ item }: { item: Item }) {
  const { t } = useT()
  const failed = item.state === 'failed'
  const current = failed ? -1 : item.state === 'indexed' ? PIPELINE.length - 1 : Math.max(0, PIPELINE.indexOf((item.stage ?? 'uploaded') as typeof PIPELINE[number]))
  return (
    <ol className="pipeline" aria-label="Pipeline">
      {PIPELINE.map((stage, index) => {
        const done = index < current || item.state === 'indexed'
        const active = index === current && item.state !== 'indexed' && !failed
        return (
          <li key={stage} className={`pipeline__step${done ? ' is-done' : ''}${active ? ' is-active' : ''}`} aria-current={active ? 'step' : undefined}>
            <span className="pipeline__dot" aria-hidden>{active ? <Loader2 size={12} className="spin" /> : done ? <CheckCircle2 size={12} /> : null}</span>
            {t(`status.${stage}` as StringKey)}
          </li>
        )
      })}
      {failed && <li className="pipeline__step is-failed">{t('status.failed')}</li>}
    </ol>
  )
}

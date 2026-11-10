import { CheckCircle, Download, Eye, FilePlus2, RefreshCw, Replace, Search, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { useT, type StringKey } from '../i18n'
import { MenuButton } from '../layout/Shell'
import { formatDate, formatSize, useApp } from '../state'
import type { DocumentRow } from '../types'
import { UploadPanel } from './UploadPanel'

export function StatusBadge({ row }: { row: DocumentRow }) {
  const { t } = useT()
  const stage = row.status === 'processing' && row.job ? row.job.stage : row.status
  return (
    <span className={`status status--${row.status}`} title={row.error ?? undefined}>
      {t(`status.${stage}` as StringKey)}
    </span>
  )
}

export function DocumentsPage() {
  const { t, locale } = useT()
  const { role, refreshStats } = useApp()
  const admin = role === 'admin'
  const [rows, setRows] = useState<DocumentRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [type, setType] = useState('')
  const [history, setHistory] = useState(false)
  const [upload, setUpload] = useState<{ replace: DocumentRow | null } | null>(null)

  const load = useCallback(() => {
    api.documents(history)
      .then((data) => { setRows(data); setError(null) })
      .catch(() => setError(t('errors.network')))
    refreshStats()
  }, [history, refreshStats, t])
  useEffect(load, [load])

  // Rafraichit tant qu'une indexation est en cours
  useEffect(() => {
    if (!rows?.some((r) => r.status === 'processing' || r.status === 'uploaded')) return
    const timer = setTimeout(load, 1500)
    return () => clearTimeout(timer)
  }, [rows, load])

  const act = async (action: () => Promise<unknown>) => {
    try {
      await action()
    } catch (err) {
      window.alert(err instanceof ApiError && err.kind === 'unauthorized' ? t('errors.unauthorized') : err instanceof Error ? err.message : t('errors.server'))
    }
    load()
  }

  const types = [...new Set((rows ?? []).map((r) => r.doc_type))].sort()
  const q = query.trim().toLowerCase()
  const filtered = (rows ?? []).filter((r) => (!type || r.doc_type === type) && (!q || `${r.title} ${r.file_name} ${r.reference ?? ''}`.toLowerCase().includes(q)))

  return (
    <div className="page">
      <header className="page-header">
        <MenuButton />
        <div>
          <h1 className="page-title">{t('docs.title')}</h1>
          <p className="muted">{t('docs.subtitle')}</p>
        </div>
        {admin && (
          <div className="page-header__actions">
            <button type="button" className="btn btn--secondary" onClick={() => window.confirm(`${t('docs.reindexAll')} ?`) && act(api.reindexAll)}><RefreshCw size={16} aria-hidden /> <span>{t('docs.reindexAll')}</span></button>
            <button type="button" className="btn btn--primary" onClick={() => setUpload({ replace: null })}><FilePlus2 size={16} aria-hidden /> <span>{t('docs.upload')}</span></button>
          </div>
        )}
      </header>

      {upload && admin && <UploadPanel replaceTarget={upload.replace} onClose={() => setUpload(null)} onChanged={load} />}

      <div className="toolbar">
        <label className="search-field">
          <Search size={16} aria-hidden /><span className="sr-only">{t('docs.search')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('docs.search')} />
        </label>
        <label className="sr-only" htmlFor="doc-type-filter">{t('docs.col.type')}</label>
        <select id="doc-type-filter" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">{t('settings.allTypes')}</option>
          {types.map((x) => <option key={x}>{x}</option>)}
        </select>
        {admin && <label className="switch"><input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} /><span className="small">{t('docs.history')}</span></label>}
      </div>

      {error && <div className="inline-error" role="alert">{error}<button type="button" className="btn btn--secondary" onClick={load}>{t('errors.retry')}</button></div>}
      {!rows && !error ? (
        <div className="skeleton-list" aria-busy="true">{[0, 1, 2, 3, 4].map((i) => <span key={i} className="skeleton skeleton--row" />)}</div>
      ) : rows && filtered.length === 0 ? (
        <p className="empty muted">{t('docs.empty')}</p>
      ) : rows && (
        <div className="table-scroll">
          <table className="doc-table">
            <thead>
              <tr>
                <th scope="col">{t('docs.col.title')}</th>
                <th scope="col">{t('docs.col.type')}</th>
                <th scope="col">{t('docs.col.version')}</th>
                <th scope="col">{t('docs.col.status')}</th>
                <th scope="col" className="num">{t('docs.col.chunks')}</th>
                <th scope="col">{t('docs.col.uploaded')}</th>
                <th scope="col" className="num">{t('docs.col.size')}</th>
                <th scope="col"><span className="sr-only">{t('docs.col.actions')}</span></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id} className={row.status === 'superseded' || row.status === 'removed' ? 'is-muted' : undefined}>
                  <th scope="row">
                    <span className="doc-title">{row.title}</span>
                    <span className="muted small">{row.reference ?? row.file_name}{row.is_base ? ` · ${t('docs.base')}` : ''}</span>
                    {row.error && <span className="error-text small">{row.error}</span>}
                  </th>
                  <td data-label={t('docs.col.type')}>{row.doc_type}</td>
                  <td data-label={t('docs.col.version')}>{[row.version, formatDate(row.effective_date, locale)].filter((x) => x && x !== '—').join(' · ') || '—'}</td>
                  <td data-label={t('docs.col.status')}><StatusBadge row={row} /></td>
                  <td data-label={t('docs.col.chunks')} className="num">{row.chunk_count ?? '—'}</td>
                  <td data-label={t('docs.col.uploaded')}>{formatDate(row.uploaded_at, locale)}{row.uploaded_by ? <span className="muted small"> · {row.uploaded_by}</span> : null}</td>
                  <td data-label={t('docs.col.size')} className="num">{formatSize(row.size)}</td>
                  <td className="row-actions">
                    <a className="icon-btn" href={api.documentFileUrl(row.id)} target="_blank" rel="noopener noreferrer" aria-label={`${row.extension === '.pdf' ? t('docs.preview') : t('docs.download')} — ${row.title}`} title={row.extension === '.pdf' ? t('docs.preview') : t('docs.download')}>
                      {row.extension === '.pdf' ? <Eye size={16} /> : <Download size={16} />}
                    </a>
                    {admin && row.status === 'pending_review' && (
                      <button type="button" className="icon-btn" onClick={() => act(() => api.approve(row.id))} aria-label={`${t('docs.approve')} — ${row.title}`} title={t('docs.approve')}><CheckCircle size={16} /></button>
                    )}
                    {admin && !['superseded', 'removed'].includes(row.status) && (
                      <>
                        <button type="button" className="icon-btn" onClick={() => act(() => api.reindex(row.id))} aria-label={`${t('docs.reindex')} — ${row.title}`} title={t('docs.reindex')}><RefreshCw size={16} /></button>
                        <button type="button" className="icon-btn" onClick={() => setUpload({ replace: row })} aria-label={`${t('docs.replace')} — ${row.title}`} title={t('docs.replace')}><Replace size={16} /></button>
                        <button type="button" className="icon-btn icon-btn--danger" onClick={() => window.confirm(t('docs.confirmDelete', { title: row.title })) && act(() => api.deleteDocument(row.id))} aria-label={`${t('docs.delete')} — ${row.title}`} title={t('docs.delete')}><Trash2 size={16} /></button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

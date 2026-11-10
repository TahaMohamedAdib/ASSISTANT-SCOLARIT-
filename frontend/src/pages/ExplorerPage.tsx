import { ExternalLink, Search } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { appConfig } from '../config'
import { useT, type StringKey } from '../i18n'
import { MenuButton } from '../layout/Shell'
import { useApp } from '../state'
import type { SearchHit } from '../types'

/** Recherche seule : passages bruts, scores et methode (semantique / mots-cles), sans LLM. */
export function ExplorerPage() {
  const { t } = useT()
  const { settings } = useApp()
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(8)
  const [type, setType] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async (event: FormEvent) => {
    event.preventDefault()
    if (!query.trim()) return
    setBusy(true)
    setError(null)
    try {
      setHits((await api.search(query.trim(), topK, type || null)).fragments)
    } catch {
      setError(t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <header className="page-header">
        <MenuButton />
        <div>
          <h1 className="page-title">{t('explorer.title')}</h1>
          <p className="muted">{t('explorer.subtitle')}</p>
        </div>
      </header>
      <form className="toolbar" onSubmit={run}>
        <label className="search-field search-field--grow">
          <Search size={16} aria-hidden /><span className="sr-only">{t('explorer.placeholder')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('explorer.placeholder')} />
        </label>
        <label className="field field--inline"><span className="field__label">k</span>
          <input type="number" min={appConfig.topK.min} max={20} value={topK} onChange={(e) => setTopK(Number(e.target.value))} />
        </label>
        <label className="sr-only" htmlFor="explorer-type">{t('settings.docType')}</label>
        <select id="explorer-type" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">{t('settings.allTypes')}</option>
          {(settings?.doc_types ?? []).map((x) => <option key={x}>{x}</option>)}
        </select>
        <button type="submit" className="btn btn--primary" disabled={busy || !query.trim()}>{t('common.search')}</button>
      </form>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {busy ? <div className="skeleton-list">{[0, 1, 2].map((i) => <span key={i} className="skeleton skeleton--block" />)}</div>
        : hits === null ? <p className="empty muted">{t('explorer.empty')}</p>
          : hits.length === 0 ? <p className="empty muted">{t('explorer.none')}</p>
            : (
              <ol className="hits">
                {hits.map((hit, index) => (
                  <li key={hit.chunk_id} className="source-card">
                    <div className="source-card__head">
                      <span className="source-card__num">{index + 1}</span>
                      <div>
                        <p className="source-card__title">{hit.title ?? hit.file}</p>
                        <p className="source-card__meta">{hit.document_type} · p. {hit.page}{hit.section ? ` · ${hit.section}` : ''}</p>
                      </div>
                    </div>
                    <p className="source-card__passage">{hit.excerpt}</p>
                    <div className="source-card__foot">
                      <span className="score">{t('sources.score', { score: hit.score.toFixed(3) })}</span>
                      {hit.methods.map((m) => <span key={m} className="badge">{t(`debug.method.${m}` as StringKey)}</span>)}
                      {hit.document_id && <a className="btn btn--ghost btn--sm" href={api.documentFileUrl(hit.document_id, hit.page)} target="_blank" rel="noopener noreferrer"><ExternalLink size={14} aria-hidden /> {t('sources.open')}</a>}
                    </div>
                  </li>
                ))}
              </ol>
            )}
    </div>
  )
}

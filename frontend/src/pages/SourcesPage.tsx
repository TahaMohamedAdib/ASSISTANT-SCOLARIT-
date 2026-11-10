import { ExternalLink } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useT } from '../i18n'
import { MenuButton } from '../layout/Shell'
import { formatDate } from '../state'
import type { DocumentRow } from '../types'

/** Base de connaissances par type de document + documents les plus cites dans les reponses. */
export function SourcesPage() {
  const { t, locale } = useT()
  const [docs, setDocs] = useState<DocumentRow[] | null>(null)
  const [cited, setCited] = useState<{ document_id: string; title: string; count: number }[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    Promise.all([api.documents(), api.sourceStats()])
      .then(([d, s]) => { setDocs(d.filter((x) => x.status === 'indexed')); setCited(s) })
      .catch(() => setError(true))
  }, [])

  const byType = new Map<string, DocumentRow[]>()
  for (const doc of docs ?? []) byType.set(doc.doc_type, [...(byType.get(doc.doc_type) ?? []), doc])
  const max = Math.max(1, ...(cited ?? []).map((c) => c.count))

  return (
    <div className="page">
      <header className="page-header">
        <MenuButton />
        <div>
          <h1 className="page-title">{t('sourcesPage.title')}</h1>
          <p className="muted">{t('sourcesPage.subtitle')}</p>
        </div>
      </header>
      {error && <div className="inline-error" role="alert">{t('errors.network')}</div>}

      <section className="card">
        <h2 className="section-title">{t('sourcesPage.mostCited')}</h2>
        {!cited ? <span className="skeleton skeleton--block" /> : cited.length === 0 ? <p className="muted">{t('sourcesPage.noCitations')}</p> : (
          <ol className="bars">
            {cited.slice(0, 10).map((c) => (
              <li key={c.document_id}>
                <span className="bars__label">{c.title}</span>
                <span className="bars__track"><span style={{ inlineSize: `${(c.count / max) * 100}%` }} /></span>
                <span className="bars__value">{t('sourcesPage.citations', { n: c.count })}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      {!docs && !error ? <div className="skeleton-list">{[0, 1, 2].map((i) => <span key={i} className="skeleton skeleton--block" />)}</div> : (
        <div className="type-grid">
          {[...byType.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([type, list]) => (
            <section key={type} className="card">
              <h2 className="section-title">{type} <span className="muted small">({list.length})</span></h2>
              <ul className="doc-list">
                {list.map((d) => (
                  <li key={d.id}>
                    <a href={api.documentFileUrl(d.id)} target="_blank" rel="noopener noreferrer">
                      <span>{d.title}</span> <ExternalLink size={14} aria-hidden />
                    </a>
                    <span className="muted small">{[d.reference, d.version, formatDate(d.effective_date, locale)].filter((x) => x && x !== '—').join(' · ')}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}

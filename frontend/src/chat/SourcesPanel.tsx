import { ExternalLink, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { api } from '../api/client'
import { useT } from '../i18n'
import type { Citation } from '../types'

type Props = { citations: Citation[]; active: number | null; onClose: () => void; answer?: string }

const words = (text: string) =>
  new Set(text.toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '').match(/[a-z0-9]{3,}/g) ?? [])

/**
 * Decoupe le passage en phrases et marque celles qui recouvrent le plus la reponse :
 * l'utilisateur voit tout de suite la phrase qui justifie l'affirmation.
 */
export function highlightPassage(passage: string, answer = '') {
  const target = words(answer)
  // Une ligne = une unite (les PDF coupent souvent les phrases en lignes) ; sinon decoupage par phrase.
  const parts = passage.split(/(?<=[.;:!?])\s+|\n+/).filter((part) => part.trim())
  if (!target.size) return parts.map((text) => ({ text, hit: false }))
  const scored = parts.map((text) => {
    const tokens = [...words(text)]
    const overlap = tokens.filter((token) => target.has(token)).length
    return { text, score: tokens.length ? overlap / Math.sqrt(tokens.length) : 0 }
  })
  const best = Math.max(...scored.map((p) => p.score))
  return scored.map(({ text, score }) => ({ text, hit: best > 0 && score >= best * 0.6 }))
}

/** Panneau lateral des sources d'une reponse : titre, type, page/section, passage surligne, score, lien. */
export function SourcesPanel({ citations, active, onClose, answer }: Props) {
  const { t } = useT()
  const panel = useRef<HTMLElement>(null)
  const sorted = [...citations].sort((a, b) => Number(b.cited) - Number(a.cited) || a.id - b.id)

  useEffect(() => {
    const target = active ? panel.current?.querySelector<HTMLElement>(`[data-cite="${active}"]`) : null
    ;(target ?? panel.current)?.focus({ preventScroll: true })
    target?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [active, citations])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="sources-panel" ref={panel} tabIndex={-1} aria-label={t('sources.title')}>
      <header className="sources-panel__header">
        <h2>{t('sources.title')}</h2>
        <button type="button" className="icon-btn" onClick={onClose} aria-label={t('sources.close')}><X size={18} /></button>
      </header>
      {sorted.length === 0 ? (
        <p className="muted">{t('sources.empty')}</p>
      ) : (
        <ol className="sources-panel__list">
          {sorted.map((c) => (
            <li key={c.id} data-cite={c.id} tabIndex={-1} className={`source-card${c.id === active ? ' source-card--active' : ''}${c.attachment ? ' source-card--attachment' : ''}`}>
              <div className="source-card__head">
                <span className="source-card__num">{c.id}</span>
                <div>
                  <p className="source-card__title">{c.title}</p>
                  <p className="source-card__meta">
                    {c.attachment ? t('sources.attachment') : c.doc_type}
                    {c.page ? ` · ${t('sources.page', { page: c.page })}` : ''}
                    {c.reference ? ` · ${c.reference}` : ''}
                  </p>
                </div>
              </div>
              {c.section && <p className="source-card__section">{c.section}</p>}
              <blockquote className="source-card__passage">
                {highlightPassage(c.passage, answer).map((part, i) => (
                  <span key={i}>{part.hit ? <mark>{part.text}</mark> : part.text} </span>
                ))}
              </blockquote>
              <div className="source-card__foot">
                <span className="score" title={t('sources.score', { score: c.score.toFixed(2) })}>
                  <span className="score__bar"><span style={{ inlineSize: `${Math.round(Math.max(0, Math.min(1, c.score)) * 100)}%` }} /></span>
                  {c.score.toFixed(2)}
                </span>
                {!c.cited && <span className="badge">{t('sources.notCited')}</span>}
                {c.document_id && !c.attachment && (
                  <a className="btn btn--ghost btn--sm" href={api.documentFileUrl(c.document_id, c.page)} target="_blank" rel="noopener noreferrer">
                    <ExternalLink size={14} aria-hidden /> {t('sources.open')}
                  </a>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </aside>
  )
}

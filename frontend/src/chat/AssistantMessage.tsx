import { Check, Copy, FileWarning, Mail, Phone, RefreshCw, RotateCcw, SearchX, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { useT, type StringKey } from '../i18n'
import { useApp } from '../state'
import type { ChatMessage, Citation } from '../types'
import { Markdown } from './Markdown'

type Props = {
  message: ChatMessage
  isLast: boolean
  busy: boolean
  onCite: (message: ChatMessage, n: number | null) => void
  onRegenerate: () => void
  onRetry: () => void
  onFollowup: (question: string) => void
  onRephrase: () => void
  onFeedback: (id: string, feedback: ChatMessage['feedback']) => void
}

const errorKey: Record<string, StringKey> = {
  network: 'errors.network', timeout: 'errors.timeout', llm: 'errors.llm', server: 'errors.server', unauthorized: 'errors.unauthorized',
}

export function AssistantMessage({ message, isLast, busy, onCite, onRegenerate, onRetry, onFollowup, onRephrase, onFeedback }: Props) {
  const { t } = useT()
  const { chat, contact } = useApp()
  const [copied, setCopied] = useState(false)
  const [commenting, setCommenting] = useState(false)
  const [comment, setComment] = useState('')
  const [thanks, setThanks] = useState(false)

  const citations = message.citations ?? []
  const cited = citations.filter((c) => c.cited)
  const valid = new Set(citations.map((c) => c.id))
  const notFound = message.found === false && !message.pending && !message.error && !message.stopped
  const fromAttachment = cited.some((c) => c.attachment)
  const persisted = !message.pending && !message.id.startsWith('pending-')

  const copy = async () => {
    await navigator.clipboard?.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const rate = async (rating: 1 | -1, text?: string) => {
    onFeedback(message.id, { rating, comment: text ?? null })
    try {
      await api.feedback(message.id, rating, text)
      if (rating === 1 || text !== undefined) setThanks(true)
    } catch {
      onFeedback(message.id, message.feedback ?? null)
    }
  }

  if (message.pending && !message.content) {
    return (
      <div className="assistant" aria-live="polite">
        <div className="thinking" role="status">
          <span className="thinking__dot" aria-hidden />
          {t(`chat.stage.${message.stage ?? 'searching'}` as StringKey)}
        </div>
      </div>
    )
  }

  return (
    <article className="assistant" aria-live={message.pending ? 'polite' : undefined}>
      {notFound ? (
        <div className="notfound">
          <SearchX aria-hidden className="notfound__icon" />
          <div>
            <p className="notfound__title">{t('notfound.title')}</p>
            <p>{t('notfound.body')}</p>
            <p className="notfound__contact">
              <a href={`mailto:${contact.email}`}><Mail size={16} aria-hidden /> {contact.email}</a>
              <a href={`tel:${contact.phone.replace(/\s/g, '')}`}><Phone size={16} aria-hidden /> {contact.phone}</a>
            </p>
            {isLast && <button type="button" className="btn btn--secondary" onClick={onRephrase}>{t('notfound.rephrase')}</button>}
          </div>
        </div>
      ) : (
        message.content && <Markdown text={message.content} validCitations={valid} onCite={(n) => onCite(message, n)} />
      )}

      {message.partial && <p className="note"><FileWarning size={16} aria-hidden /> {t('notfound.partial')}</p>}
      {fromAttachment && <p className="note note--attachment">{t('chat.fromAttachment')}</p>}
      {message.stopped && <p className="note">{t('chat.stopped')}</p>}
      {message.error && (
        <div className="inline-error" role="alert">
          <span>{message.error === 'quota' ? t('errors.quota', { min: message.retryAfterMin ?? '…' }) : t(errorKey[message.error] ?? 'errors.server')}</span>
          {isLast && <button type="button" className="btn btn--secondary" onClick={onRetry}><RotateCcw size={16} aria-hidden /> {t('errors.retry')}</button>}
        </div>
      )}

      {!message.pending && cited.length > 0 && (
        <button type="button" className="sources-chip" onClick={() => onCite(message, null)}>
          <span className="sources-chip__stack" aria-hidden>{cited.slice(0, 3).map((c) => <span key={c.id}>{c.id}</span>)}</span>
          {t('chat.sources', { n: cited.length })}
        </button>
      )}

      {persisted && message.content && (
        <div className="actions" role="toolbar" aria-label="Actions">
          <button type="button" className="icon-btn" onClick={copy} aria-label={copied ? t('actions.copied') : t('actions.copy')} title={copied ? t('actions.copied') : t('actions.copy')}>
            {copied ? <Check size={18} /> : <Copy size={18} />}
          </button>
          {isLast && (
            <button type="button" className="icon-btn" onClick={onRegenerate} disabled={busy} aria-label={t('actions.regenerate')} title={t('actions.regenerate')}>
              <RefreshCw size={18} />
            </button>
          )}
          {!message.error && (
            <>
              <button type="button" className="icon-btn" aria-pressed={message.feedback?.rating === 1} onClick={() => rate(1)} aria-label={t('actions.up')} title={t('actions.up')}>
                <ThumbsUp size={18} />
              </button>
              <button type="button" className="icon-btn" aria-pressed={message.feedback?.rating === -1} onClick={() => { setCommenting(true); void rate(-1) }} aria-label={t('actions.down')} title={t('actions.down')}>
                <ThumbsDown size={18} />
              </button>
            </>
          )}
          {thanks && <span className="actions__thanks" role="status">{t('actions.thanks')}</span>}
        </div>
      )}

      {commenting && (
        <form className="feedback-form" onSubmit={(e) => { e.preventDefault(); void rate(-1, comment.trim()); setCommenting(false) }}>
          <label className="sr-only" htmlFor={`fb-${message.id}`}>{t('actions.commentPlaceholder')}</label>
          <input id={`fb-${message.id}`} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t('actions.commentPlaceholder')} maxLength={1000} autoFocus />
          <button type="button" className="btn btn--ghost" onClick={() => setCommenting(false)}>{t('common.cancel')}</button>
          <button type="submit" className="btn btn--primary">{t('actions.sendFeedback')}</button>
        </form>
      )}

      {isLast && !busy && (message.followups?.length ?? 0) > 0 && (
        <div className="followups">
          <p className="followups__label">{t('actions.followups')}</p>
          {message.followups!.map((q) => (
            <button type="button" key={q} className="followup" onClick={() => onFollowup(q)}>{q}</button>
          ))}
        </div>
      )}

      {chat.transparency && message.debug && !message.pending && <DebugPanel message={message} />}
    </article>
  )
}

function DebugPanel({ message }: { message: ChatMessage }) {
  const { t } = useT()
  const debug = message.debug!
  const methods = (c: { methods: string[] }) => c.methods.map((m) => t(`debug.method.${m}` as StringKey)).join(' + ')
  return (
    <details className="debug">
      <summary>{t('settings.transparency')}</summary>
      {debug.rewritten_query && <p><strong>{t('debug.rewritten')} :</strong> {debug.rewritten_query}</p>}
      <p><strong>{t('debug.retrieved')} :</strong></p>
      <ol>
        {(message.citations ?? []).map((c: Citation) => (
          <li key={c.id}>
            {c.title} · p.{c.page} · {c.score.toFixed(2)} · {methods(c)}{c.cited ? ' ✓' : ''}
          </li>
        ))}
      </ol>
      {debug.timings && (
        <p><strong>{t('debug.timings')} :</strong> {Object.entries(debug.timings).map(([k, v]) => `${k.replace('_ms', '')} ${(v / 1000).toFixed(1)} s`).join(' · ')}</p>
      )}
    </details>
  )
}

import { Play, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api, type EvalRun } from '../api/client'
import { useT } from '../i18n'
import { MenuButton } from '../layout/Shell'
import { formatDate, useApp } from '../state'

/** Valeurs deja en pourcentage (0-100). */
const pct = (value: number | string | null | undefined) => (value == null || value === '' ? '—' : `${Number(value).toFixed(1)} %`)
/** Fractions (0-1). */
const frac = (value: number | null | undefined) => (value == null ? '—' : `${(value * 100).toFixed(1)} %`)

/** Tableau de bord : retours, questions sans reponse, evaluation. */
export function AdminPage() {
  const { t, locale } = useT()
  const { role } = useApp()
  const [feedback, setFeedback] = useState<Awaited<ReturnType<typeof api.adminFeedback>> | null>(null)
  const [unanswered, setUnanswered] = useState<Awaited<ReturnType<typeof api.unanswered>> | null>(null)
  const [evals, setEvals] = useState<{ runs: EvalRun[]; offline: Record<string, string | null>[] } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    Promise.all([api.adminFeedback(), api.unanswered(), api.evalResults()])
      .then(([f, u, e]) => { setFeedback(f); setUnanswered(u); setEvals(e); setError(null) })
      .catch(() => setError(t('errors.unauthorized')))
  }, [t])
  useEffect(() => { if (role === 'admin') load() }, [role, load])

  const running = evals?.runs.some((r) => r.status === 'running')
  useEffect(() => {
    if (!running) return
    const timer = setTimeout(load, 2000)
    return () => clearTimeout(timer)
  }, [running, evals, load])

  if (role !== 'admin') {
    return <div className="page"><header className="page-header"><MenuButton /><h1 className="page-title">{t('admin.title')}</h1></header><p className="empty muted">{t('admin.loginRequired')}</p></div>
  }

  const start = async (mode: 'retrieval' | 'full') => {
    await api.runEval(mode, 10).catch(() => setError(t('errors.server')))
    load()
  }
  const total = feedback ? feedback.up + feedback.down : 0

  return (
    <div className="page">
      <header className="page-header"><MenuButton /><h1 className="page-title">{t('admin.title')}</h1></header>
      {error && <div className="inline-error" role="alert">{error}</div>}

      <div className="admin-grid">
        <section className="card">
          <h2 className="section-title">{t('admin.feedback')}</h2>
          {!feedback ? <span className="skeleton skeleton--block" /> : (
            <>
              <div className="kpis">
                <div className="kpi"><ThumbsUp size={18} aria-hidden /><strong>{feedback.up}</strong></div>
                <div className="kpi"><ThumbsDown size={18} aria-hidden /><strong>{feedback.down}</strong></div>
                <div className="kpi"><strong>{total ? `${Math.round((feedback.up / total) * 100)} %` : '—'}</strong><span className="muted small">{t('admin.satisfaction')}</span></div>
              </div>
              <h3 className="sub-title">{t('admin.worst')}</h3>
              {feedback.negative.length === 0 ? <p className="muted">{t('admin.noFeedback')}</p> : (
                <ul className="feedback-list">
                  {feedback.negative.map((f, i) => (
                    <li key={i}>
                      <p className="feedback-list__q">{f.question}</p>
                      {f.comment && <p className="feedback-list__c">« {f.comment} »</p>}
                      <details><summary className="small muted">{formatDate(f.created_at, locale)}</summary><p className="small">{f.answer}</p></details>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>

        <section className="card">
          <h2 className="section-title">{t('admin.unanswered')}</h2>
          <p className="muted small">{t('admin.unansweredHint')}</p>
          {!unanswered ? <span className="skeleton skeleton--block" /> : unanswered.length === 0 ? <p className="muted">{t('admin.noUnanswered')}</p> : (
            <ul className="unanswered">
              {unanswered.map((u) => (
                <li key={u.question}><span>{u.question}</span><span className="badge">{t('admin.times', { n: u.count })}</span></li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="card">
        <h2 className="section-title">{t('admin.eval')}</h2>
        <p className="muted small">{t('admin.evalHint')}</p>
        <div className="toolbar">
          <button type="button" className="btn btn--primary" disabled={running} onClick={() => start('retrieval')}><Play size={16} aria-hidden /> {t('admin.runRetrieval')}</button>
          <button type="button" className="btn btn--secondary" disabled={running} onClick={() => start('full')}>{t('admin.runFull')}</button>
          {running && <span className="muted" role="status">{t('admin.running')}</span>}
        </div>
        {evals && evals.runs.length > 0 && (
          <div className="table-scroll">
            <table className="doc-table">
              <thead><tr><th scope="col">Date</th><th scope="col">Mode</th><th scope="col" className="num">Recall@k</th><th scope="col" className="num">FullRecall@k</th><th scope="col" className="num">MRR</th><th scope="col" className="num">Correctness</th></tr></thead>
              <tbody>
                {evals.runs.map((run) => (
                  <tr key={run.id}>
                    <th scope="row">{new Date(run.started_at).toLocaleString(locale === 'fr' ? 'fr-FR' : 'en-GB')}</th>
                    <td>{run.mode}{run.status !== 'done' && <span className={`status status--${run.status === 'failed' ? 'failed' : 'processing'}`}> {run.status}</span>}{run.error && <span className="error-text small"> {run.error}</span>}</td>
                    <td className="num">{frac(run.summary?.recall_at_k)}</td>
                    <td className="num">{frac(run.summary?.full_recall_at_k)}</td>
                    <td className="num">{run.summary ? run.summary.mrr.toFixed(3) : '—'}</td>
                    <td className="num">{pct(run.summary?.generation?.answer_accuracy_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {evals && evals.offline.length > 0 && (
          <>
            <h3 className="sub-title">{t('admin.offline')}</h3>
            <div className="table-scroll">
              <table className="doc-table">
                <thead><tr><th scope="col">Configuration</th><th scope="col" className="num">Correctness</th><th scope="col" className="num">Fully correct</th><th scope="col" className="num">Faithfulness</th><th scope="col" className="num">Correct refusal</th><th scope="col" className="num">False refusal</th></tr></thead>
                <tbody>
                  {evals.offline.map((row) => (
                    <tr key={row.name}>
                      <th scope="row">{row.name}</th>
                      <td className="num">{pct(row.correctness_pct)}</td><td className="num">{pct(row.fully_correct_pct)}</td>
                      <td className="num">{pct(row.faithfulness_pct)}</td><td className="num">{pct(row.correct_refusal_pct)}</td><td className="num">{pct(row.false_refusal_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  )
}

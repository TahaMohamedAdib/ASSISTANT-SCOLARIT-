import { FormEvent, useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { BookOpen, Bot, ChevronRight, Compass, FileText, FolderOpen, GraduationCap, LibraryBig, LoaderCircle, MessageSquareText, Search, Send, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react'
import { ApiError, ragApi } from './api/client'
import type { AskResponse, IndexedDocument, Source } from './types'

type Tab = 'conversation' | 'sources' | 'documents' | 'search'
type Message = { question: string; response: AskResponse }
const tabs: { id: Tab; label: string; icon: typeof MessageSquareText }[] = [
  { id: 'conversation', label: 'Conversation', icon: MessageSquareText }, { id: 'sources', label: 'Sources', icon: LibraryBig },
  { id: 'documents', label: 'Documents', icon: FolderOpen }, { id: 'search', label: 'Explorer', icon: Search },
]

function userMessage(error: unknown) {
  if (!(error instanceof ApiError)) return 'Impossible de joindre l’API. Vérifiez que le backend est démarré.'
  if (error.status === 422) return 'La question ou les paramètres saisis ne sont pas valides.'
  if (error.status === 502) return 'Le modèle de langage ne répond pas. Vérifiez Ollama.'
  if (error.status === 503) return 'Le service d’indexation est indisponible. Lancez d’abord l’ingestion.'
  return error.message
}

function AnswerText({ answer, sources, onCitation }: { answer: string; sources: Source[]; onCitation: (source: Source) => void }) {
  return <p className="answer-text">{answer.split(/(\[\d+\])/g).map((part, index) => {
    const match = part.match(/^\[(\d+)\]$/); if (!match) return part
    const source = sources[Number(match[1]) - 1]
    return source ? <button className="citation" type="button" key={`${part}-${index}`} onClick={() => onCitation(source)}>{part}</button> : <span className="citation invalid" key={`${part}-${index}`}>{part}</span>
  })}</p>
}

function SourceCard({ source, selected, onSelect }: { source: Source; selected: boolean; onSelect: () => void }) {
  return <motion.button layout type="button" className={`source-card ${selected ? 'selected' : ''}`} onClick={onSelect} whileHover={{ y: -4 }}>
    <span className="source-score">{Math.round(source.score * 100)}%</span><FileText size={18} /><strong>{source.reference ?? source.file}</strong>
    <span>{source.section ?? 'Section non précisée'} · p. {source.page}</span><em>{source.excerpt}</em><span className="source-date">{source.date ?? 'Date non précisée'} <ChevronRight size={14} /></span>
  </motion.button>
}

function Settings({ topK, setTopK, type, setType, documents }: { topK: number; setTopK: (value: number) => void; type: string | null; setType: (value: string | null) => void; documents: IndexedDocument[] }) {
  const types = useMemo(() => [...new Set(documents.map((document) => document.type).filter((value): value is string => Boolean(value)))], [documents])
  return <section className="settings glass" aria-label="Paramètres de recherche"><div className="setting-intro"><SlidersHorizontal size={17} /><span>Recherche réglée sur</span></div>
    <label><span>Fragments</span><input type="number" min="1" max="20" value={topK} onChange={(event) => setTopK(Math.max(1, Math.min(20, Number(event.target.value) || 1)))} /></label>
    <label><span>Type de document</span><select value={type ?? ''} onChange={(event) => setType(event.target.value || null)}><option value="">Tous les documents</option>{types.map((documentType) => <option key={documentType} value={documentType}>{documentType}</option>)}</select></label>
    <div className="index-status"><span className="status-dot" />{documents.length || '—'} documents indexés</div></section>
}

export default function App() {
  const [tab, setTab] = useState<Tab>('conversation'); const [documents, setDocuments] = useState<IndexedDocument[]>([])
  const [question, setQuestion] = useState(''); const [debugQuestion, setDebugQuestion] = useState(''); const [topK, setTopK] = useState(6); const [type, setType] = useState<string | null>(null)
  const [history, setHistory] = useState<Message[]>([]); const [sources, setSources] = useState<Source[]>([]); const [selectedSource, setSelectedSource] = useState<Source | null>(null); const [debugSources, setDebugSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(false); const [error, setError] = useState<string | null>(null)
  useEffect(() => { ragApi.documents().then(setDocuments).catch((reason) => setError(userMessage(reason))) }, [])
  async function ask(event: FormEvent) { event.preventDefault(); if (!question.trim() || loading) return; setLoading(true); setError(null); try { const response = await ragApi.ask(question.trim(), topK, type); setHistory((messages) => [...messages, { question: question.trim(), response }]); setSources(response.sources); setSelectedSource(response.sources[0] ?? null); setQuestion('') } catch (reason) { setError(userMessage(reason)) } finally { setLoading(false) } }
  async function runDebugSearch(event: FormEvent) { event.preventDefault(); if (!debugQuestion.trim() || loading) return; setLoading(true); setError(null); try { const response = await ragApi.search(debugQuestion.trim(), topK, type); setDebugSources(response.fragments) } catch (reason) { setError(userMessage(reason)) } finally { setLoading(false) } }
  const showSources = (source: Source) => { setSelectedSource(source); setTab('sources') }
  return <main className="app-shell"><div className="ambient ambient-one" /><div className="ambient ambient-two" />
    <aside className="sidebar glass"><div className="brand-mark"><GraduationCap size={25} /><span>EI<span>H</span></span></div><nav aria-label="Navigation principale">{tabs.map(({ id, label, icon: Icon }) => <button key={id} type="button" className={tab === id ? 'active' : ''} onClick={() => setTab(id)} title={label}><Icon size={20} /><span>{label}</span>{id === 'sources' && sources.length > 0 && <b>{sources.length}</b>}</button>)}</nav><div className="sidebar-footer"><ShieldCheck size={19} /><span>Corpus vérifié</span></div></aside>
    <section className="workspace"><header className="topbar"><div><p className="eyebrow"><Sparkles size={14} /> École d’Ingénieurs Hélianthe</p><h1>Votre espace <em>scolarité.</em></h1><p className="subtitle">Des réponses fiables, ancrées dans les documents officiels.</p></div><div className="topbar-actions"><span className="official-badge"><ShieldCheck size={16} /> Sources officielles</span><div className="avatar">EH</div></div></header>
      <Settings topK={topK} setTopK={setTopK} type={type} setType={setType} documents={documents} />
      <AnimatePresence>{error && <motion.div className="alert" role="alert" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><Compass size={18} />{error}</motion.div>}</AnimatePresence>
      <AnimatePresence mode="wait">
        {tab === 'conversation' && <motion.section key="conversation" className="conversation-panel glass panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}><div className="panel-heading"><div><span className="panel-kicker"><Bot size={15} /> Assistant EIH</span><h2>Conversation</h2></div><span className="online"><i /> En ligne</span></div><div className="messages" aria-live="polite">{!history.length && <div className="empty-state"><div className="bot-orb"><Bot size={28} /></div><strong>Bonjour, comment puis-je vous aider ?</strong><span>Posez une question sur vos études, stages ou la vie étudiante.</span><div className="suggestions">{['Attestation de scolarité', 'Durée minimale du PFE', 'Contester une note'].map((item) => <button key={item} type="button" onClick={() => setQuestion(item)}>{item}<ChevronRight size={14} /></button>)}</div></div>}{history.map((message, index) => <motion.article className="exchange" key={`${message.question}-${index}`} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}><div className="message student"><span>Vous</span><p>{message.question}</p></div><div className={`message assistant ${message.response.found ? '' : 'refusal'}`}><span><Bot size={14} /> Assistant EIH</span><AnswerText answer={message.response.answer} sources={message.response.sources} onCitation={showSources} />{!message.response.found && <small>Réponse hors corpus — aucune information n’a été inventée.</small>}<small>{message.response.latency_ms} ms · {message.response.sources.length} sources</small></div></motion.article>)}</div><form className="question-form" onSubmit={ask}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Posez votre question ici…" rows={2} disabled={loading} aria-label="Votre question" /><button className="send-button" type="submit" disabled={loading || !question.trim()} aria-label="Envoyer la question">{loading ? <LoaderCircle className="spin" size={20} /> : <Send size={20} />}</button></form><p className="disclaimer"><ShieldCheck size={13} /> Les réponses sont limitées aux documents officiels de l’école.</p></motion.section>}
        {tab === 'sources' && <motion.section key="sources" className="source-panel glass panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-heading"><div><span className="panel-kicker"><LibraryBig size={15} /> Traçabilité</span><h2>Sources retenues</h2><p>Chaque source provient du corpus officiel.</p></div></div>{sources.length ? <div className="source-grid">{sources.map((source) => <SourceCard key={source.id} source={source} selected={selectedSource?.id === source.id} onSelect={() => setSelectedSource(source)} />)}</div> : <div className="empty-state compact"><BookOpen size={28} /><strong>Aucune source à afficher.</strong><span>Les citations apparaîtront ici après votre première question.</span></div>}</motion.section>}
        {tab === 'documents' && <motion.section key="documents" className="documents-panel glass panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-heading"><div><span className="panel-kicker"><FolderOpen size={15} /> Bibliothèque</span><h2>Documents indexés</h2><p>Le catalogue officiel disponible à la recherche.</p></div><div className="document-count">{documents.length}</div></div><div className="document-list">{documents.map((document) => <article key={document.file}><div className="document-icon"><FileText size={20} /></div><div><strong>{document.reference}</strong><span>{document.type} · {document.date}</span><small>{document.file}</small></div><span className="chunk-count">{document.chunk_count} fragments</span><ChevronRight size={18} /></article>)}</div></motion.section>}
        {tab === 'search' && <motion.section key="search" className="search-panel glass panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><div className="panel-heading"><div><span className="panel-kicker"><Search size={15} /> Outil avancé</span><h2>Explorer le corpus</h2><p>Inspectez les passages les plus pertinents, sans génération.</p></div></div><form className="debug-form" onSubmit={runDebugSearch}><Search size={20} /><input value={debugQuestion} onChange={(event) => setDebugQuestion(event.target.value)} placeholder="Rechercher dans les documents…" disabled={loading} aria-label="Question de débogage" /><button className="primary-button" type="submit" disabled={loading || !debugQuestion.trim()}>{loading ? 'Recherche…' : 'Rechercher'}</button></form><div className="debug-list">{debugSources.map((source, index) => <motion.article key={source.id} className="debug-result" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}><header><strong><span>#{index + 1}</span>{source.reference}</strong><b>{source.score.toFixed(4)}</b></header><p>{source.excerpt}</p><footer>p. {source.page} · {source.section ?? 'Section non précisée'}</footer></motion.article>)}</div></motion.section>}
      </AnimatePresence></section></main>
}

import { Paperclip } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { AssistantMessage } from '../chat/AssistantMessage'
import { Composer, type ComposerHandle } from '../chat/Composer'
import { SettingsPopover } from '../chat/SettingsPopover'
import { SourcesPanel } from '../chat/SourcesPanel'
import { useChat } from '../chat/useChat'
import { appConfig } from '../config'
import { useT } from '../i18n'
import { MenuButton, useShell } from '../layout/Shell'
import { formatDate, useApp } from '../state'
import type { ChatMessage } from '../types'

export function ChatPage() {
  const { t, locale } = useT()
  const { chat, stats, settings, backendUp, refreshStats } = useApp()
  const { conversations, refreshConversations } = useShell()
  const { conversationId = null } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const composer = useRef<ComposerHandle>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const [panel, setPanel] = useState<{ messageId: string; active: number | null } | null>(null)
  const [pendingAttachment, setPendingAttachment] = useState<{ name: string; uploading: boolean; error?: string } | null>(null)

  const onConversation = useCallback((id: string, created: boolean) => {
    if (created) navigate(`/c/${id}`, { replace: true })
    refreshConversations()
  }, [navigate, refreshConversations])

  const {
    messages, attachments, setAttachments, loading, loadError, streaming, send, regenerate, stop, retry, setFeedback, reset,
  } = useChat({ conversationId, topK: chat.topK, docType: chat.docType, onConversation })

  // "Nouvelle conversation" depuis la barre laterale
  const fresh = (location.state as { fresh?: number } | null)?.fresh
  useEffect(() => {
    if (fresh) {
      reset()
      setPanel(null)
      setPendingAttachment(null)
      composer.current?.focus()
    }
  }, [fresh, reset])

  // Changement de conversation : on ferme le panneau. Mais pas lors du passage "/" -> "/c/<id>"
  // d'une conversation qui vient d'etre creee (la navigation est appliquee en transition et peut
  // arriver apres un clic de l'utilisateur sur une citation).
  const previousId = useRef(conversationId)
  useEffect(() => {
    if (previousId.current !== null && previousId.current !== conversationId) {
      setPanel(null)
      setPendingAttachment(null)
    }
    previousId.current = conversationId
  }, [conversationId])

  useEffect(() => {
    const el = scroller.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages])

  useEffect(refreshStats, [refreshStats])

  const onScroll = () => {
    const el = scroller.current
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const ask = (text: string) => {
    stickToBottom.current = true
    setPendingAttachment(null)
    void send(text)
  }

  const attach = async (file: File) => {
    const max = settings?.max_upload_mb ?? 20
    if (file.size > max * 1024 * 1024) {
      setPendingAttachment({ name: file.name, uploading: false, error: t('upload.tooBig', { max }) })
      return
    }
    setPendingAttachment({ name: file.name, uploading: true })
    try {
      let id = conversationId
      if (!id) {
        id = (await api.createConversation()).id
        navigate(`/c/${id}`, { replace: true })
        refreshConversations()
      }
      const result = await api.attach(id, file)
      setAttachments((current) => [...current, { id: result.id, file_name: result.file_name, created_at: new Date().toISOString() }])
      setPendingAttachment(null)
    } catch (error) {
      setPendingAttachment({ name: file.name, uploading: false, error: error instanceof ApiError && error.kind === 'rejected' ? error.message : t('errors.server') })
    }
  }

  const openSources = (message: ChatMessage, n: number | null) => setPanel({ messageId: message.id, active: n })
  const panelMessage = panel ? messages.find((m) => m.id === panel.messageId) : null
  const title = conversations?.find((c) => c.id === conversationId)?.title
  const empty = messages.length === 0 && !loading && !loadError
  const lastAssistant = messages.map((m) => m.role).lastIndexOf('assistant')
  const accept = settings?.allowed_extensions.join(',')

  const composerEl = (
    <Composer
      ref={composer}
      busy={streaming}
      disabled={backendUp === false}
      onSend={ask}
      onStop={stop}
      onAttach={attach}
      accept={accept}
      attachment={pendingAttachment}
      onRemoveAttachment={() => setPendingAttachment(null)}
    />
  )

  return (
    <div className={`chat-page${panelMessage ? ' chat-page--panel' : ''}`}>
      <div className="chat-page__main">
        <header className="page-header page-header--chat">
          <MenuButton />
          <h1 className="page-header__title">{title ?? ''}</h1>
          <SettingsPopover />
        </header>

        {empty ? (
          <div className="empty-state">
            <h1 className="greeting">{t('chat.greeting')}</h1>
            <p className="muted">{t('chat.subtitle')}</p>
            <div className="empty-state__composer">{composerEl}</div>
            <div className="chips">
              {appConfig.suggestions[locale].map((s) => (
                <button key={s.label} type="button" className="chip" onClick={() => ask(s.question)} disabled={backendUp === false}>{s.label}</button>
              ))}
            </div>
            <p className="corpus-line small muted">
              {stats == null ? ' ' : stats.indexed_documents > 0
                ? t('chat.corpus', { n: stats.indexed_documents, date: formatDate(stats.last_updated, locale) })
                : t('chat.corpusEmpty')}
            </p>
          </div>
        ) : (
          <>
            <div className="messages" ref={scroller} onScroll={onScroll}>
              <div className="column">
                {loading && <div className="skeleton-list" aria-busy="true">{[0, 1, 2].map((i) => <span key={i} className="skeleton skeleton--block" />)}</div>}
                {loadError && (
                  <div className="inline-error" role="alert">
                    {loadError.kind === 'not_found' ? t('errors.server') : t('errors.network')}
                    <button type="button" className="btn btn--secondary" onClick={() => navigate('/')}>{t('sidebar.new')}</button>
                  </div>
                )}
                {attachments.length > 0 && (
                  <ul className="attachments">
                    {attachments.map((a) => <li key={a.id}><Paperclip size={14} aria-hidden /> {t('chat.attached', { name: a.file_name })}</li>)}
                  </ul>
                )}
                {messages.map((m, index) => m.role === 'user' ? (
                  <div key={m.id} className="user-msg"><p className="sr-only">{t('chat.you')} :</p><div className="user-msg__bubble">{m.content}</div></div>
                ) : (
                  <AssistantMessage
                    key={m.id}
                    message={m}
                    isLast={index === lastAssistant}
                    busy={streaming}
                    onCite={openSources}
                    onRegenerate={() => { stickToBottom.current = true; void regenerate() }}
                    onRetry={retry}
                    onFollowup={ask}
                    onRephrase={() => composer.current?.setText([...messages].reverse().find((x) => x.role === 'user')?.content ?? '')}
                    onFeedback={setFeedback}
                  />
                ))}
              </div>
            </div>
            <div className="composer-dock">
              <div className="column">
                {composerEl}
                <p className="disclaimer">{t('chat.disclaimer')}</p>
              </div>
            </div>
          </>
        )}
      </div>
      {panelMessage && (
        <>
          <div className="scrim scrim--panel" onClick={() => setPanel(null)} aria-hidden />
          <SourcesPanel citations={panelMessage.citations ?? []} active={panel!.active} answer={panelMessage.content} onClose={() => setPanel(null)} />
        </>
      )}
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ChatMessage, ConversationDetail, StoredMessage } from '../types'

export function fromStored(message: StoredMessage): ChatMessage {
  const restored: ChatMessage = { id: message.id, role: message.role, content: message.content, created_at: message.created_at, feedback: message.feedback, ...message.payload }
  // Les erreurs enregistrees cote serveur sont des messages bruts : on les ramene a une categorie connue.
  if (restored.error) restored.error = /quota/i.test(restored.error) ? 'quota' : 'llm'
  return restored
}

type Options = {
  conversationId: string | null
  topK: number
  docType: string | null
  /** Appele des que le serveur a attribue un identifiant a une nouvelle conversation. */
  onConversation: (id: string, created: boolean) => void
}

/** Etat d'une conversation : chargement, envoi en flux (SSE), arret, regeneration. */
export function useChat({ conversationId, topK, docType, onConversation }: Options) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<ApiError | null>(null)
  const [streaming, setStreaming] = useState(false)
  const [attachments, setAttachments] = useState<ConversationDetail['attachments']>([])
  const controller = useRef<AbortController | null>(null)
  /** Conversation actuellement alimentee par un flux : ne pas la recharger depuis le serveur. */
  const live = useRef<string | null>(null)

  const load = useCallback(async (id: string) => {
    setLoading(true)
    setLoadError(null)
    try {
      const detail = await api.conversation(id)
      setMessages(detail.messages.map(fromStored))
      setAttachments(detail.attachments)
    } catch (error) {
      setLoadError(error instanceof ApiError ? error : new ApiError('network', 'network'))
      setMessages([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!conversationId) {
      if (!live.current) {
        setMessages([])
        setAttachments([])
      }
      return
    }
    if (live.current === conversationId) return
    controller.current?.abort()
    live.current = null
    void load(conversationId)
  }, [conversationId, load])

  const patchLast = (patch: (message: ChatMessage) => ChatMessage) =>
    setMessages((current) => {
      const next = [...current]
      next[next.length - 1] = patch(next[next.length - 1])
      return next
    })

  const run = useCallback(async (text: string, regenerate = false) => {
    if (streaming) return
    const abort = new AbortController()
    controller.current = abort
    setStreaming(true)
    const placeholder: ChatMessage = { id: `pending-${Date.now()}`, role: 'assistant', content: '', pending: true, stage: 'searching' }
    setMessages((current) => {
      const base = regenerate ? current.slice(0, current.map((m) => m.role).lastIndexOf('assistant')) : current
      const withUser = regenerate ? base : [...base, { id: `user-${Date.now()}`, role: 'user' as const, content: text }]
      return [...withUser, placeholder]
    })
    live.current = conversationId ?? '__new__'
    try {
      const payload = { conversation_id: conversationId, message: text, top_k: topK, doc_type: docType, regenerate }
      for await (const { event, data } of api.chat(payload, abort.signal)) {
        if (event === 'conversation') {
          const created = data.conversation_id !== conversationId
          live.current = data.conversation_id
          onConversation(data.conversation_id, created)
        } else if (event === 'status') patchLast((m) => ({ ...m, stage: data.stage }))
        else if (event === 'meta') patchLast((m) => ({ ...m, citations: data.citations, debug: { ...m.debug, rewritten_query: data.rewritten_query } }))
        else if (event === 'token') patchLast((m) => ({ ...m, content: m.content + data.text, stage: 'generating' }))
        else if (event === 'done') {
          patchLast((m) => ({
            ...m, id: data.message_id, content: data.answer, citations: data.citations, found: data.found, partial: data.partial,
            followups: data.followups, debug: data.debug, pending: false, stage: undefined,
          }))
          onConversation(data.conversation_id, false)
        } else if (event === 'error') {
          const quota = data.code === 'quota'
          patchLast((m) => ({ ...m, pending: false, stage: undefined, error: quota ? 'quota' : 'llm', retryAfterMin: data.retry_after_min }))
        }
      }
    } catch (error) {
      if (abort.signal.aborted) patchLast((m) => ({ ...m, pending: false, stopped: true, stage: undefined }))
      else patchLast((m) => ({ ...m, pending: false, stage: undefined, error: error instanceof ApiError ? error.kind : 'network' }))
    } finally {
      setStreaming(false)
      controller.current = null
    }
  }, [conversationId, docType, onConversation, streaming, topK])

  const send = useCallback((text: string) => run(text.trim()), [run])
  const regenerate = useCallback(() => run('', true), [run])
  const stop = useCallback(() => controller.current?.abort(), [])
  /** Apres une erreur reseau : on rejoue la derniere question. */
  const retry = useCallback(() => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    if (conversationId) void run('', true)
    else {
      setMessages((current) => current.slice(0, -2))
      void run(lastUser.content)
    }
  }, [conversationId, messages, run])

  const setFeedback = useCallback((id: string, feedback: ChatMessage['feedback']) => {
    setMessages((current) => current.map((m) => (m.id === id ? { ...m, feedback } : m)))
  }, [])

  const reset = useCallback(() => {
    controller.current?.abort()
    live.current = null
    setMessages([])
    setAttachments([])
  }, [])

  return { messages, attachments, setAttachments, loading, loadError, streaming, send, regenerate, stop, retry, setFeedback, reset, reload: load }
}

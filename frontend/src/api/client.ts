import { appConfig } from '../config'
import type {
  AppSettings, ChatEvent, Conversation, ConversationDetail, DocumentRow, Job, SearchHit, Stats,
} from '../types'

const BASE = appConfig.apiBaseUrl
const TOKEN_KEY = 'eih-admin-token'

export type ErrorKind = 'network' | 'timeout' | 'server' | 'unauthorized' | 'conflict' | 'rejected' | 'not_found'

export class ApiError extends Error {
  constructor(
    public readonly kind: ErrorKind,
    message: string,
    public readonly status = 0,
    public readonly code?: string,
    public readonly documentId?: string,
  ) {
    super(message)
  }
}

export const authToken = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string | null) => (token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY)),
}

function authHeaders(): Record<string, string> {
  const token = authToken.get()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function toError(response: Response): Promise<ApiError> {
  let message = `Erreur ${response.status}`
  let code: string | undefined
  let documentId: string | undefined
  try {
    const payload = await response.json()
    const detail = payload.detail
    if (typeof detail === 'string') message = detail
    else if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      message = detail.message ?? message
      code = detail.code
      documentId = detail.document_id
    }
  } catch {
    // reponse non JSON : le statut HTTP suffit
  }
  const kind: ErrorKind =
    response.status === 401 ? 'unauthorized'
      : response.status === 404 ? 'not_found'
        : response.status === 409 ? 'conflict'
          : response.status === 422 ? 'rejected'
            : 'server'
  return new ApiError(kind, message, response.status, code, documentId)
}

async function send(path: string, init: RequestInit = {}, timeoutMs = appConfig.requestTimeoutMs): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort('timeout'), timeoutMs)
  init.signal?.addEventListener('abort', () => controller.abort(init.signal?.reason))
  try {
    const response = await fetch(`${BASE}${path}`, { ...init, headers: { ...authHeaders(), ...init.headers }, signal: controller.signal })
    if (!response.ok) throw await toError(response)
    return response
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted && controller.signal.reason === 'timeout') throw new ApiError('timeout', 'timeout')
    if (init.signal?.aborted) throw error
    throw new ApiError('network', 'network')
  } finally {
    clearTimeout(timer)
  }
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init)
  return (response.status === 204 ? undefined : await response.json()) as T
}

const body = (payload: unknown): RequestInit => ({
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
})

/** Lit un flux text/event-stream (POST, donc pas d'EventSource) et emet les evenements parses. */
export async function* parseSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
      let event = 'message'
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (data.length) yield { event, data: JSON.parse(data.join('\n')) } as ChatEvent
    }
  }
}

export type ChatPayload = {
  conversation_id?: string | null
  message: string
  top_k?: number
  doc_type?: string | null
  regenerate?: boolean
}

export const api = {
  health: () => json<{ status: string; indexed_fragments: number }>('/api/health'),
  config: () => json<AppSettings>('/api/config'),
  stats: () => json<Stats>('/api/stats'),

  login: (password: string) => json<{ token: string; role: string }>('/api/auth/login', body({ password })),
  me: () => json<{ role: 'admin' | 'student'; admin_enabled: boolean }>('/api/auth/me'),

  async *chat(payload: ChatPayload, signal: AbortSignal): AsyncGenerator<ChatEvent> {
    // Pas de delai global : une generation peut durer ; l'utilisateur peut l'arreter.
    const response = await send('/api/chat', { ...body(payload), signal }, 10 * 60_000)
    if (!response.body) throw new ApiError('server', 'empty stream')
    yield* parseSse(response.body)
  },

  conversations: (q = '') => json<Conversation[]>(`/api/conversations${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  conversation: (id: string) => json<ConversationDetail>(`/api/conversations/${id}`),
  createConversation: () => json<Conversation>('/api/conversations', body({})),
  renameConversation: (id: string, title: string) =>
    json<Conversation>(`/api/conversations/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) }),
  deleteConversation: (id: string) => json<void>(`/api/conversations/${id}`, { method: 'DELETE' }),
  attach: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return json<{ id: string; file_name: string; chunks: number }>(`/api/conversations/${id}/attachments`, { method: 'POST', body: form }, )
  },

  feedback: (message_id: string, rating: 1 | -1, comment?: string) => json<{ ok: boolean }>('/api/feedback', body({ message_id, rating, comment })),

  search: (question: string, top_k: number, type: string | null) =>
    json<{ fragments: SearchHit[] }>('/api/search', body({ question, top_k, filters: { type } })),

  documents: (history = false) => json<DocumentRow[]>(`/api/documents${history ? '?history=true' : ''}`),
  documentFileUrl: (id: string, page?: number) => `${BASE}/api/documents/${id}/file${page ? `#page=${page}` : ''}`,
  upload: (file: File, fields: Record<string, string | boolean>) => {
    const form = new FormData()
    form.append('file', file)
    for (const [key, value] of Object.entries(fields)) form.append(key, String(value))
    return json<{ document: DocumentRow; job_id: string | null }>('/api/documents', { method: 'POST', body: form })
  },
  job: (id: string) => json<Job & { document_id: string }>(`/api/ingestion/${id}`),
  deleteDocument: (id: string) => json<void>(`/api/documents/${id}`, { method: 'DELETE' }),
  reindex: (id: string) => json<{ job_id: string }>(`/api/documents/${id}/reindex`, { method: 'POST' }),
  approve: (id: string) => json<{ job_id: string }>(`/api/documents/${id}/approve`, { method: 'POST' }),
  reindexAll: () => json<{ jobs: string[] }>('/api/documents/reindex-all', { method: 'POST' }),

  sourceStats: () => json<{ document_id: string; title: string; count: number }[]>('/api/sources/stats'),
  adminFeedback: () => json<{ up: number; down: number; negative: { question: string; answer: string; comment: string | null; created_at: string }[] }>('/api/admin/feedback'),
  unanswered: () => json<{ question: string; count: number; last_asked: string }[]>('/api/admin/unanswered'),
  runEval: (mode: 'retrieval' | 'full', sample = 10) => json<{ run_id: string }>('/api/eval/run', body({ mode, sample })),
  evalResults: () => json<{ runs: EvalRun[]; offline: Record<string, string | null>[] }>('/api/eval/results'),
}

export type EvalRun = {
  id: string
  status: 'running' | 'done' | 'failed'
  mode: string
  started_at: string
  finished_at: string | null
  error: string | null
  summary: {
    questions: number
    top_k: number
    recall_at_k: number
    full_recall_at_k: number
    mrr: number
    by_category_full_recall: Record<string, number>
    generation?: Record<string, number>
  } | null
}

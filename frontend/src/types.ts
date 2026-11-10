export type Citation = {
  id: number
  chunk_id: string
  document_id: string | null
  title: string
  doc_type: string | null
  reference: string | null
  file: string
  page: number
  section: string | null
  passage: string
  score: number
  methods: string[]
  official: boolean
  attachment: boolean
  date: string | null
  cited: boolean
}

export type Debug = {
  original_query?: string
  rewritten_query?: string | null
  retrieval?: { n: number; title: string; page: number; section: string | null; score: number; methods: string[] }[]
  best_score?: number | null
  threshold?: number
  timings?: Record<string, number>
}

export type Stage = 'rewriting' | 'searching' | 'generating'

export type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at?: string
  citations?: Citation[]
  found?: boolean
  partial?: boolean
  followups?: string[]
  debug?: Debug
  stopped?: boolean
  error?: string
  /** Quota du LLM atteint : delai avant nouvel essai (minutes). */
  retryAfterMin?: number
  feedback?: { rating: number; comment: string | null } | null
  /** Etat local pendant la diffusion */
  pending?: boolean
  stage?: Stage
}

export type Conversation = { id: string; title: string; created_at: string; updated_at: string }

export type StoredMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  payload: Partial<Pick<ChatMessage, 'citations' | 'found' | 'partial' | 'followups' | 'debug' | 'stopped' | 'error'>>
  feedback: { rating: number; comment: string | null } | null
}

export type ConversationDetail = Conversation & {
  messages: StoredMessage[]
  attachments: { id: string; file_name: string; created_at: string }[]
}

export type Job = { id: string; stage: string; progress: number; error: string | null }

export type DocumentRow = {
  id: string
  title: string
  doc_type: string
  department: string | null
  effective_date: string | null
  version: string | null
  official: boolean
  reference: string | null
  file_name: string
  size: number
  extension: string
  status: string
  is_base: boolean
  page_count: number | null
  chunk_count: number | null
  uploaded_by: string | null
  uploaded_at: string
  indexed_at: string | null
  replaces_id: string | null
  error: string | null
  job: Job | null
}

export type Stats = { indexed_documents: number; last_updated: string | null; processing: number; chunks: number }

export type AppSettings = {
  contact_email: string
  contact_phone: string
  max_upload_mb: number
  allowed_extensions: string[]
  doc_types: string[]
  require_review: boolean
  admin_enabled: boolean
  default_top_k: number
}

export type SearchHit = {
  id: string
  chunk_id: string
  file: string
  title: string | null
  document_id: string | null
  document_type: string | null
  reference: string | null
  date: string | null
  page: number
  section: string | null
  excerpt: string
  score: number
  methods: string[]
}

export type ChatEvent =
  | { event: 'conversation'; data: { conversation_id: string } }
  | { event: 'status'; data: { stage: Stage } }
  | { event: 'meta'; data: { rewritten_query: string | null; citations: Citation[] } }
  | { event: 'token'; data: { text: string } }
  | {
      event: 'done'
      data: {
        message_id: string
        conversation_id: string
        found: boolean
        partial: boolean
        answer: string
        citations: Citation[]
        followups: string[]
        debug: Debug
      }
    }
  | { event: 'error'; data: { code: string; message: string; retry_after_min?: number } }

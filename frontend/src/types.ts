export type Source = {
  id: string
  chunk_id: string
  file: string
  reference: string | null
  date: string | null
  page: number
  section: string | null
  excerpt: string
  score: number
}

export type AskResponse = {
  answer: string
  found: boolean
  sources: Source[]
  invalid_citations: number[]
  latency_ms: number
}

export type SearchResponse = {
  fragments: Source[]
}

export type IndexedDocument = {
  file: string
  reference: string | null
  type: string | null
  date: string | null
  version: string | null
  status: string | null
  page_count: number
  chunk_count: number
}

import type { AskResponse, IndexedDocument, SearchResponse } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(`${API_BASE_URL}${path}`, init)
  if (!response.ok) {
    let message = `Erreur ${response.status}`
    try {
      const { detail } = await response.json()
      if (typeof detail === 'string') {
        message = detail
      } else if (Array.isArray(detail)) {
        const details = detail.flatMap((item) => typeof item?.msg === 'string' ? [item.msg] : [])
        if (details.length) message = details.join(' · ')
      }
    } catch {
      // The HTTP status remains useful when an intermediary returns non-JSON.
    }
    throw new ApiError(response.status, message)
  }
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init)
  return response.json() as Promise<T>
}

function query<T>(path: string, question: string, topK: number, type: string | null) {
  return json<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, top_k: topK, filters: { type } }),
  })
}

export const ragApi = {
  documents: (signal?: AbortSignal) => json<IndexedDocument[]>('/api/documents', { signal }),
  uploadDocument: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return json<IndexedDocument>('/api/documents/upload', { method: 'POST', body })
  },
  deleteDocument: async (filename: string) => {
    await request(`/api/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' })
  },
  ask: (question: string, topK: number, type: string | null) =>
    query<AskResponse>('/api/ask', question, topK, type),
  search: (question: string, topK: number, type: string | null) =>
    query<SearchResponse>('/api/search', question, topK, type),
}

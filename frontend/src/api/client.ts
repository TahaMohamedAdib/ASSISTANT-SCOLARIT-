import type { AskResponse, IndexedDocument, SearchResponse } from '../types'

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    let message = `Erreur ${response.status}`
    try {
      const payload = await response.json()
      message = typeof payload.detail === 'string' ? payload.detail : message
    } catch {
      // The HTTP status remains useful when an intermediary returns non-JSON.
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export const ragApi = {
  documents: () => request<IndexedDocument[]>('/api/documents'),
  ask: (question: string, topK: number, type: string | null) =>
    request<AskResponse>('/api/ask', {
      method: 'POST',
      body: JSON.stringify({ question, top_k: topK, filters: { type } }),
    }),
  search: (question: string, topK: number, type: string | null) =>
    request<SearchResponse>('/api/search', {
      method: 'POST',
      body: JSON.stringify({ question, top_k: topK, filters: { type } }),
    }),
}

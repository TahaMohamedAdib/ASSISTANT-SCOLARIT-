import { useCallback, useEffect, useState } from 'react'
import { ApiError, ragApi } from '../api/client'
import type { IndexedDocument } from '../types'

type PendingAction = { kind: 'upload' | 'delete'; filename: string }
type Feedback = { tone: 'success' | 'error'; message: string }

function errorMessage(error: unknown): string {
  return error instanceof ApiError
    ? error.message
    : 'Impossible de joindre l’API. Vérifiez que le backend est démarré.'
}

export function useDocuments() {
  const [documents, setDocuments] = useState<IndexedDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const busy = loading || pending !== null

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setListError(null)
    try {
      const next = await ragApi.documents(signal)
      if (!signal?.aborted) setDocuments(next)
    } catch (error) {
      if (!signal?.aborted) setListError(errorMessage(error))
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  async function run(action: PendingAction, mutate: () => Promise<void>, success: string) {
    if (busy) return false
    setPending(action)
    setFeedback(null)
    try {
      await mutate()
      setFeedback({ tone: 'success', message: success })
      await refresh()
      return true
    } catch (error) {
      setFeedback({ tone: 'error', message: errorMessage(error) })
      return false
    } finally {
      setPending(null)
    }
  }

  const upload = (file: File) => run(
    { kind: 'upload', filename: file.name },
    async () => {
      const added = await ragApi.uploadDocument(file)
      setDocuments((current) => [...current.filter((document) => document.file !== added.file), added])
    },
    `« ${file.name} » a été ajouté à l’index.`,
  )

  const remove = (document: IndexedDocument) => run(
    { kind: 'delete', filename: document.file },
    async () => {
      await ragApi.deleteDocument(document.file)
      setDocuments((current) => current.filter(({ file }) => file !== document.file))
    },
    `« ${document.file} » a été supprimé de l’index.`,
  )

  return { documents, loading, listError, pending, feedback, busy, refresh, upload, remove }
}

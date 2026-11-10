/** Faux backend pour les tests de composants : routes JSON + flux SSE du chat. */
import { vi } from 'vitest'

type Handler = (init: RequestInit | undefined, url: URL) => Response | Promise<Response>

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

export function sse(events: [string, unknown][]) {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // Decoupage volontairement irregulier pour tester le tampon du parseur
      const text = events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')
      for (let i = 0; i < text.length; i += 37) controller.enqueue(encoder.encode(text.slice(i, i + 37)))
      controller.close()
    },
  })
  return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}

export const settings = {
  contact_email: 'scolarite@eih.ma', contact_phone: '+212 5 22 00 00 00', max_upload_mb: 1,
  allowed_extensions: ['.pdf', '.md', '.txt'], doc_types: ['Règlement', 'Autre'], require_review: false,
  admin_enabled: true, default_top_k: 6,
}

export function installFakeApi(routes: Record<string, Handler>) {
  const base: Record<string, Handler> = {
    'GET /api/health': () => json({ status: 'ok', indexed_fragments: 96 }),
    'GET /api/config': () => json(settings),
    'GET /api/stats': () => json({ indexed_documents: 7, last_updated: '2026-11-10T10:00:00Z', processing: 0, chunks: 96 }),
    'GET /api/auth/me': () => json({ role: 'student', admin_enabled: true }),
    'GET /api/conversations': () => json([]),
    ...routes,
  }
  const calls: { method: string; path: string; body: unknown }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input))
    const method = (init?.method ?? 'GET').toUpperCase()
    const key = `${method} ${url.pathname}`
    const handler = base[key] ?? Object.entries(base).find(([pattern]) => new RegExp(`^${pattern.replace(/:[a-z_]+/g, '[^/]+')}$`).test(key))?.[1]
    calls.push({ method, path: url.pathname, body: typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body })
    if (!handler) return json({ detail: 'not found' }, 404)
    return handler(init, url)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

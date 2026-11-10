import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { parseSse } from '../api/client'
import { AppRoutes } from '../App'
import { linkCitations } from '../chat/Markdown'
import { highlightPassage } from '../chat/SourcesPanel'
import { I18nProvider } from '../i18n'
import { AppProvider, groupByDate } from '../state'
import { installFakeApi, json, sse } from './fakeApi'

const citation = {
  id: 1, chunk_id: 'doc1:0001', document_id: 'doc1', title: 'Guide des stages et du PFE', doc_type: 'Guide PFE',
  reference: 'EIH-SRE-GUIDE-2026', file: 'guide.pdf', page: 4, section: 'Article 3 — Durée',
  passage: 'Le PFE dure 16 semaines au minimum. La soutenance a lieu en juin.', score: 0.82, methods: ['dense', 'bm25'],
  official: true, attachment: false, date: '2026-06-15', cited: false,
}

function renderApp(path = '/') {
  return render(
    <I18nProvider>
      <AppProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </AppProvider>
    </I18nProvider>,
  )
}

describe('utilitaires du chat', () => {
  it('parse un flux SSE decoupe arbitrairement', async () => {
    const events = []
    for await (const event of parseSse(sse([['token', { text: 'Bon' }], ['token', { text: 'jour' }], ['done', { found: true }]]).body!)) events.push(event)
    expect(events.map((e) => e.event)).toEqual(['token', 'token', 'done'])
  })

  it('rend les citations cliquables, y compris le format 【n】', () => {
    expect(linkCitations('Voir [1, 2] et 【3】.')).toBe('Voir [1](#cite-1)[2](#cite-2) et [3](#cite-3).')
  })

  it('surligne la phrase qui justifie la reponse', () => {
    const parts = highlightPassage(citation.passage, 'Le PFE dure au minimum 16 semaines [1].')
    expect(parts.filter((p) => p.hit).map((p) => p.text)).toEqual(['Le PFE dure 16 semaines au minimum.'])
  })

  it('regroupe l’historique par date', () => {
    const now = new Date('2026-11-10T12:00:00')
    const groups = groupByDate([
      { updated_at: '2026-11-10T09:00:00' }, { updated_at: '2026-11-09T09:00:00' }, { updated_at: '2026-11-05T09:00:00' }, { updated_at: '2026-09-01T09:00:00' },
    ], now)
    expect([groups.today.length, groups.yesterday.length, groups.week.length, groups.older.length]).toEqual([1, 1, 1, 1])
  })
})

describe('ecran de conversation', () => {
  it('diffuse la reponse, affiche les citations et ouvre le panneau des sources', async () => {
    const calls = installFakeApi({
      'POST /api/chat': () => sse([
        ['conversation', { conversation_id: 'c1' }],
        ['status', { stage: 'searching' }],
        ['meta', { rewritten_query: null, citations: [citation] }],
        ['status', { stage: 'generating' }],
        ['token', { text: 'Le PFE dure au minimum ' }],
        ['token', { text: '**16 semaines** [1].' }],
        ['done', {
          message_id: 'm1', conversation_id: 'c1', found: true, partial: false, answer: 'Le PFE dure au minimum **16 semaines** [1].',
          citations: [{ ...citation, cited: true }], followups: ['Quand a lieu la soutenance ?'], debug: {},
        }],
      ]),
      'GET /api/conversations/c1': () => json({ id: 'c1', title: 'PFE', messages: [], attachments: [] }),
    })
    const user = userEvent.setup()
    renderApp()

    expect(await screen.findByRole('heading', { name: /comment puis-je vous aider/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/posez votre question/i), 'Durée du PFE ?{Enter}')

    expect(await screen.findByText('16 semaines')).toBeInTheDocument()
    expect(screen.getByText('Durée du PFE ?')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/api/chat')?.body).toMatchObject({ message: 'Durée du PFE ?', top_k: 5 })
    expect(await screen.findByRole('button', { name: 'Quand a lieu la soutenance ?' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Source 1' }))
    const panel = await screen.findByRole('complementary', { name: 'Sources' })
    expect(within(panel).getByText('Guide des stages et du PFE')).toBeInTheDocument()
    expect(within(panel).getByText('Le PFE dure 16 semaines au minimum.').tagName).toBe('MARK')
    expect(within(panel).getByRole('link', { name: /ouvrir le document/i })).toHaveAttribute('href', expect.stringContaining('/api/documents/doc1/file#page=4'))
  })

  it('affiche l’etat « introuvable » avec le contact et permet de reformuler', async () => {
    installFakeApi({
      'POST /api/chat': () => sse([
        ['conversation', { conversation_id: 'c2' }],
        ['meta', { rewritten_query: null, citations: [] }],
        ['token', { text: "Je ne trouve pas cette information dans les documents de l'École." }],
        ['done', { message_id: 'm2', conversation_id: 'c2', found: false, partial: false, answer: "Je ne trouve pas cette information dans les documents de l'École.", citations: [], followups: [], debug: {} }],
      ]),
      'GET /api/conversations/c2': () => json({ id: 'c2', title: 'x', messages: [], attachments: [] }),
    })
    const user = userEvent.setup()
    renderApp()
    await user.type(await screen.findByLabelText(/posez votre question/i), 'Menu de la cantine ?{Enter}')

    expect(await screen.findByText(/pas trouvé cette information/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /scolarite@eih.ma/ })).toHaveAttribute('href', 'mailto:scolarite@eih.ma')
    await user.click(screen.getByRole('button', { name: /reformuler/i }))
    expect(screen.getByLabelText(/posez votre question/i)).toHaveValue('Menu de la cantine ?')
  })

  it('montre une erreur reseau avec un bouton Reessayer', async () => {
    installFakeApi({ 'POST /api/chat': () => { throw new TypeError('Failed to fetch') } })
    const user = userEvent.setup()
    renderApp()
    await user.type(await screen.findByLabelText(/posez votre question/i), 'Bonjour ?{Enter}')
    expect(await screen.findByText(/impossible de joindre le serveur/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /réessayer/i })).toBeInTheDocument()
  })

  it('explique clairement un quota de LLM atteint', async () => {
    installFakeApi({
      'POST /api/chat': () => sse([
        ['conversation', { conversation_id: 'c3' }],
        ['meta', { rewritten_query: null, citations: [citation] }],
        ['error', { code: 'quota', message: 'Quota', retry_after_min: 7 }],
      ]),
      'GET /api/conversations/c3': () => json({ id: 'c3', title: 'x', messages: [], attachments: [] }),
    })
    const user = userEvent.setup()
    renderApp()
    await user.type(await screen.findByLabelText(/posez votre question/i), 'Durée du PFE ?{Enter}')
    expect(await screen.findByText(/quota gratuit du modèle de langage est atteint\. Réessayez dans environ 7 min/i)).toBeInTheDocument()
  })

  it('affiche un bandeau quand le backend est injoignable', async () => {
    installFakeApi({ 'GET /api/health': () => { throw new TypeError('Failed to fetch') } })
    renderApp()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/injoignable/i))
  })
})

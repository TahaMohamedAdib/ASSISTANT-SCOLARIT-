import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { UploadPanel } from '../pages/UploadPanel'
import { AppProvider } from '../state'
import { installFakeApi, json } from './fakeApi'

const document = { id: 'd9', title: 'Règlement du parking', status: 'uploaded' }

function renderPanel(onChanged = vi.fn()) {
  render(
    <I18nProvider>
      <AppProvider>
        <UploadPanel replaceTarget={null} onClose={() => undefined} onChanged={onChanged} />
      </AppProvider>
    </I18nProvider>,
  )
  return onChanged
}

const file = (name: string, content = '# Parking\nOuvert de 7h à 22h.') => new File([content], name, { type: 'text/markdown' })

describe('televersement admin', () => {
  it('televerse avec metadonnees puis suit le pipeline jusqu’a « Indexé »', async () => {
    let polls = 0
    const calls = installFakeApi({
      'POST /api/documents': () => json({ document, job_id: 'j1' }, 202),
      'GET /api/ingestion/j1': () => json(++polls < 2 ? { id: 'j1', stage: 'embedding', progress: 0.6, error: null } : { id: 'j1', stage: 'indexed', progress: 1, error: null }),
    })
    const user = userEvent.setup()
    const onChanged = renderPanel()

    await user.upload(await screen.findByTestId('upload-input'), file('parking.md'))
    const title = screen.getByLabelText('Titre')
    expect(title).toHaveValue('parking')
    await user.clear(title)
    await user.type(title, 'Règlement du parking')
    await user.click(screen.getByRole('button', { name: 'Téléverser' }))

    expect(await screen.findByText(/le document est maintenant utilisé/i, {}, { timeout: 4000 })).toBeInTheDocument()
    const form = calls.find((c) => c.path === '/api/documents')!.body as FormData
    expect(form.get('title')).toBe('Règlement du parking')
    expect((form.get('file') as File).name).toBe('parking.md')
    expect(onChanged).toHaveBeenCalled()
  })

  it('refuse un format non accepte avant tout envoi', async () => {
    const calls = installFakeApi({})
    const user = userEvent.setup({ applyAccept: false })
    renderPanel()
    await user.upload(await screen.findByTestId('upload-input'), file('virus.exe', 'MZ'))
    expect(screen.getByText('Format non accepté.')).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/documents')).toBe(false)
  })

  it('propose de remplacer la version existante en cas de doublon', async () => {
    const calls = installFakeApi({
      'POST /api/documents': (init) => (init?.body as FormData).get('replace_id')
        ? json({ document, job_id: null }, 202)
        : json({ detail: { code: 'duplicate', message: 'Déjà présent', document_id: 'd1' } }, 409),
    })
    const user = userEvent.setup()
    renderPanel()
    await user.upload(await screen.findByTestId('upload-input'), file('parking.md'))
    await user.click(screen.getByRole('button', { name: 'Téléverser' }))
    expect(await screen.findByText('Ce fichier est déjà dans le corpus.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /remplacer par une nouvelle version/i }))
    const last = calls.filter((c) => c.path === '/api/documents').at(-1)!.body as FormData
    expect(last.get('replace_id')).toBe('d1')
  })
})

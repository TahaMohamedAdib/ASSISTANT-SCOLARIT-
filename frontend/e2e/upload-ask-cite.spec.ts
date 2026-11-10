import { expect, test } from '@playwright/test'

/** Parcours complet : un admin televerse un document, un etudiant pose une question, la reponse le cite. */
test('televerser -> poser une question -> la reponse cite le nouveau document', async ({ page, isMobile }) => {
  const title = `Règlement de la bibliothèque ${test.info().project.name}`
  const content = [
    `# ${title}`,
    '## Article 2 — Emprunts',
    'Chaque étudiant peut emprunter au maximum 5 ouvrages pour une durée de 21 jours, renouvelable une fois.',
    '## Article 3 — Retards',
    "Tout retard entraîne une suspension du droit d'emprunt.",
  ].join('\n')

  // 1. Connexion administrateur via le menu utilisateur
  await page.goto('/documents')
  if (isMobile) await page.getByRole('button', { name: 'Ouvrir le menu' }).click()
  await page.getByRole('button', { name: /Étudiant/ }).click()
  await page.getByLabel('Mot de passe administrateur').fill('e2e-admin')
  await page.getByRole('button', { name: 'Se connecter' }).click()
  if (isMobile) await page.getByRole('button', { name: 'Fermer', exact: true }).click()

  // 2. Televersement avec metadonnees et suivi du pipeline
  await page.getByRole('button', { name: /Ajouter des documents/ }).click()
  await page.getByTestId('upload-input').setInputFiles({ name: 'bibliotheque.md', mimeType: 'text/markdown', buffer: Buffer.from(content) })
  await page.getByLabel('Titre').fill(title)
  await page.getByLabel('Type de document').selectOption('Règlement')
  await page.getByRole('button', { name: 'Téléverser', exact: true }).click()
  await expect(page.getByText('le document est maintenant utilisé par l’assistant', { exact: false })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('row', { name: new RegExp(title) }).getByText('Indexé')).toBeVisible()

  // 3. Question dans une nouvelle conversation
  await page.goto('/')
  await page.getByLabel(/Posez votre question/).fill('Combien de livres puis-je emprunter à la bibliothèque ?')
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/c\//)
  await expect(page.getByText('emprunter au maximum 5 ouvrages', { exact: false }).first()).toBeVisible({ timeout: 30_000 })

  // 4. La citation ouvre le panneau des sources sur le document televerse
  await page.getByRole('button', { name: 'Source 1' }).click()
  const panel = page.getByRole('complementary', { name: 'Sources' })
  await expect(panel.getByText(title).first()).toBeVisible()
  await expect(panel.locator('mark').first()).toContainText('5 ouvrages')
  await expect(panel.getByRole('link', { name: /Ouvrir le document/ }).first()).toHaveAttribute('href', /\/api\/documents\/.+\/file/)

  // 5. La conversation est conservee dans l'historique
  if (isMobile) {
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Ouvrir le menu' }).click()
  }
  const current = page.getByRole('navigation').locator('[aria-current="page"]', { hasText: 'Combien de livres puis-je emprunter' })
  await expect(current).toBeVisible()
})

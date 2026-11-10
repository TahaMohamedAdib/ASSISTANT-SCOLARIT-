import { defineConfig, devices } from '@playwright/test'

/**
 * Test de bout en bout : backend isole (frontend/e2e/server.py, port 8001, donnees temporaires,
 * LLM scripte) + frontend Vite (port 5174). L'index reel et les documents d'origine ne sont pas touches.
 * Python : le venv du projet (.venv) est utilise par defaut ; surcharger avec E2E_PYTHON.
 */
const python = process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python')

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5174', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 375, height: 812 } } },
  ],
  webServer: [
    {
      command: `"${python}" e2e/server.py`,
      url: 'http://127.0.0.1:8001/api/health',
      timeout: 120_000,
      reuseExistingServer: false,
      env: { PYTHONIOENCODING: 'utf-8' },
    },
    {
      command: 'npx vite --port 5174 --strictPort',
      url: 'http://localhost:5174',
      timeout: 60_000,
      reuseExistingServer: false,
      env: { VITE_API_BASE_URL: 'http://localhost:8001' },
    },
  ],
})

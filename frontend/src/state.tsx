/** Etat global : theme, session administrateur, configuration serveur, sante du backend, reglages du chat. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, authToken } from './api/client'
import { appConfig } from './config'
import type { AppSettings, Stats } from './types'

export type Theme = 'light' | 'dark' | 'system'
export type ChatSettings = { topK: number; docType: string | null; transparency: boolean }

type AppState = {
  theme: Theme
  setTheme: (theme: Theme) => void
  role: 'admin' | 'student'
  login: (password: string) => Promise<void>
  logout: () => void
  settings: AppSettings | null
  stats: Stats | null
  refreshStats: () => void
  backendUp: boolean | null
  recheckBackend: () => void
  chat: ChatSettings
  setChat: (patch: Partial<ChatSettings>) => void
  contact: { email: string; phone: string }
}

const AppContext = createContext<AppState | null>(null)

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback
  } catch {
    return fallback
  }
}

export function applyTheme(theme: Theme) {
  const dark = theme === 'dark' || (theme === 'system' && window.matchMedia?.('(prefers-color-scheme: dark)').matches)
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (localStorage.getItem('eih-theme') as Theme) || 'system')
  const [role, setRole] = useState<'admin' | 'student'>('student')
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [backendUp, setBackendUp] = useState<boolean | null>(null)
  const [chat, setChatState] = useState<ChatSettings>(() => readJson('eih-chat-settings', { topK: 5, docType: null, transparency: false }))

  const setTheme = useCallback((value: Theme) => {
    localStorage.setItem('eih-theme', value)
    setThemeState(value)
  }, [])
  useEffect(() => {
    applyTheme(theme)
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    const listener = () => applyTheme(theme)
    media?.addEventListener?.('change', listener)
    return () => media?.removeEventListener?.('change', listener)
  }, [theme])

  const setChat = useCallback((patch: Partial<ChatSettings>) => {
    setChatState((current) => {
      const next = { ...current, ...patch }
      localStorage.setItem('eih-chat-settings', JSON.stringify(next))
      return next
    })
  }, [])

  const refreshStats = useCallback(() => {
    api.stats().then(setStats).catch(() => undefined)
  }, [])

  const recheckBackend = useCallback(() => {
    api.health()
      .then(() => {
        setBackendUp(true)
        if (!settings) api.config().then(setSettings).catch(() => undefined)
      })
      .catch(() => setBackendUp(false))
  }, [settings])

  useEffect(() => {
    recheckBackend()
    refreshStats()
    api.me().then((me) => setRole(me.role)).catch(() => undefined)
    const timer = setInterval(recheckBackend, appConfig.healthPollMs)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = useCallback(async (password: string) => {
    const { token } = await api.login(password)
    authToken.set(token)
    setRole('admin')
  }, [])
  const logout = useCallback(() => {
    authToken.set(null)
    setRole('student')
  }, [])

  const value = useMemo<AppState>(() => ({
    theme, setTheme, role, login, logout, settings, stats, refreshStats, backendUp, recheckBackend, chat, setChat,
    contact: settings ? { email: settings.contact_email, phone: settings.contact_phone } : appConfig.fallbackContact,
  }), [theme, setTheme, role, login, logout, settings, stats, refreshStats, backendUp, recheckBackend, chat, setChat])

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used inside AppProvider')
  return context
}

/** Regroupe des conversations par date relative (aujourd'hui, hier, 7 jours, plus ancien). */
export function groupByDate<T extends { updated_at: string }>(items: T[], today = new Date()) {
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  const day = 86_400_000
  const groups: Record<'today' | 'yesterday' | 'week' | 'older', T[]> = { today: [], yesterday: [], week: [], older: [] }
  for (const item of items) {
    const time = new Date(item.updated_at).getTime()
    if (time >= start) groups.today.push(item)
    else if (time >= start - day) groups.yesterday.push(item)
    else if (time >= start - 7 * day) groups.week.push(item)
    else groups.older.push(item)
  }
  return groups
}

export function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(locale === 'fr' ? 'fr-FR' : 'en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`
}

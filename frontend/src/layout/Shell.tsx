import { AlertTriangle, Menu, RotateCcw } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { api } from '../api/client'
import { useT } from '../i18n'
import { useApp } from '../state'
import type { Conversation } from '../types'
import { Sidebar } from './Sidebar'

type ShellState = {
  conversations: Conversation[] | null
  refreshConversations: () => void
  openMenu: () => void
}
const ShellContext = createContext<ShellState | null>(null)
export const useShell = () => {
  const context = useContext(ShellContext)
  if (!context) throw new Error('useShell outside Shell')
  return context
}

/** Bouton d'ouverture du menu (mobile) a placer dans l'en-tete des pages. */
export function MenuButton() {
  const { t } = useT()
  const { openMenu } = useShell()
  return (
    <button type="button" className="icon-btn menu-btn" onClick={openMenu} aria-label={t('sidebar.menu')}>
      <Menu size={20} />
    </button>
  )
}

export function Shell() {
  const { t } = useT()
  const { backendUp, recheckBackend } = useApp()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem('eih-sidebar') === 'collapsed')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [conversations, setConversations] = useState<Conversation[] | null>(null)

  const refreshConversations = useCallback(() => {
    api.conversations().then(setConversations).catch(() => setConversations((current) => current ?? []))
  }, [])
  useEffect(refreshConversations, [refreshConversations])

  const toggle = () => {
    localStorage.setItem('eih-sidebar', collapsed ? 'open' : 'collapsed')
    setCollapsed(!collapsed)
  }

  return (
    <ShellContext.Provider value={{ conversations, refreshConversations, openMenu: () => setMobileOpen(true) }}>
      <a className="skip-link" href="#main">Aller au contenu</a>
      <div className={`shell${collapsed ? ' shell--collapsed' : ''}`}>
        <Sidebar collapsed={collapsed} onToggle={toggle} mobileOpen={mobileOpen} onCloseMobile={() => setMobileOpen(false)} />
        {mobileOpen && <div className="scrim" onClick={() => setMobileOpen(false)} aria-hidden />}
        <div className="shell__main">
          {backendUp === false && (
            <div className="banner" role="alert">
              <AlertTriangle size={16} aria-hidden />
              <span>{t('errors.backendDown')}</span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={recheckBackend}><RotateCcw size={14} aria-hidden /> {t('errors.retry')}</button>
            </div>
          )}
          <main id="main" className="shell__content">
            <Outlet />
          </main>
        </div>
      </div>
    </ShellContext.Provider>
  )
}

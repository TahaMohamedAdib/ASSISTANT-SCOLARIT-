import {
  BarChart3, BookOpen, Check, FileText, LogIn, LogOut, MessageSquare, Moon, MoreHorizontal, PanelLeftClose, PanelLeftOpen,
  Pencil, Search, SquarePen, Sun, SunMoon, Telescope, Trash2, X,
} from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, useMatch, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { locales, useT, type Locale, type StringKey } from '../i18n'
import { groupByDate, useApp, type Theme } from '../state'
import type { Conversation } from '../types'
import { useShell } from './Shell'

type Props = { collapsed: boolean; onToggle: () => void; mobileOpen: boolean; onCloseMobile: () => void }

export function Logo() {
  return <span className="logo" aria-hidden>EIH</span>
}

export function Sidebar({ collapsed, onToggle, mobileOpen, onCloseMobile }: Props) {
  const { t } = useT()
  const { role } = useApp()
  const { conversations, refreshConversations } = useShell()
  const navigate = useNavigate()
  const match = useMatch('/c/:conversationId')
  const activeId = match?.params.conversationId
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Conversation[] | null>(null)

  useEffect(() => {
    if (!query.trim()) {
      setResults(null)
      return
    }
    const timer = setTimeout(() => api.conversations(query.trim()).then(setResults).catch(() => setResults([])), 250)
    return () => clearTimeout(timer)
  }, [query, conversations])

  const list = results ?? conversations
  const groups = list ? groupByDate(list) : null
  const nav = [
    { to: '/', label: 'nav.chat', icon: MessageSquare, end: true },
    { to: '/documents', label: 'nav.documents', icon: FileText },
    { to: '/sources', label: 'nav.sources', icon: BookOpen },
    { to: '/explorer', label: 'nav.explorer', icon: Telescope },
    ...(role === 'admin' ? [{ to: '/admin', label: 'nav.admin', icon: BarChart3 }] : []),
  ] as const

  const newChat = () => {
    navigate('/', { state: { fresh: Date.now() } })
    onCloseMobile()
  }

  return (
    <nav className={`sidebar${mobileOpen ? ' sidebar--open' : ''}`} aria-label="Navigation">
      <div className="sidebar__top">
        <div className="sidebar__brand">
          <Logo />
          <span className="sidebar__name">{t('app.name')}</span>
        </div>
        <button type="button" className="icon-btn sidebar__toggle" onClick={onToggle} aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')} title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}>
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
        <button type="button" className="icon-btn sidebar__close" onClick={onCloseMobile} aria-label={t('common.close')}><X size={18} /></button>
      </div>

      <button type="button" className="sidebar__new" onClick={newChat} title={t('sidebar.new')}>
        <SquarePen size={18} aria-hidden /> <span>{t('sidebar.new')}</span>
      </button>

      <ul className="sidebar__nav">
        {nav.map(({ to, label, icon: Icon, ...rest }) => (
          <li key={to}>
            <NavLink to={to} end={'end' in rest} onClick={onCloseMobile} title={t(label as StringKey)}>
              <Icon size={18} aria-hidden /> <span>{t(label as StringKey)}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <div className="sidebar__history">
        <label className="search-field">
          <Search size={16} aria-hidden />
          <span className="sr-only">{t('sidebar.search')}</span>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('sidebar.search')} />
        </label>
        {!groups ? (
          <div className="skeleton-list" aria-busy="true">{[0, 1, 2, 3].map((i) => <span key={i} className="skeleton" />)}</div>
        ) : list!.length === 0 ? (
          <p className="muted small sidebar__empty">{t('sidebar.empty')}</p>
        ) : (
          (['today', 'yesterday', 'week', 'older'] as const).map((key) => groups[key].length > 0 && (
            <section key={key}>
              <h2 className="sidebar__group">{t(`sidebar.${key}` as StringKey)}</h2>
              <ul>
                {groups[key].map((c) => (
                  <HistoryItem key={c.id} conversation={c} active={c.id === activeId} onChanged={refreshConversations}
                    onOpen={() => { navigate(`/c/${c.id}`); onCloseMobile() }}
                    onDeleted={() => { refreshConversations(); if (c.id === activeId) navigate('/') }} />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>

      <UserMenu />
    </nav>
  )
}

function HistoryItem({ conversation, active, onOpen, onChanged, onDeleted }: {
  conversation: Conversation; active: boolean; onOpen: () => void; onChanged: () => void; onDeleted: () => void
}) {
  const { t } = useT()
  const [menu, setMenu] = useState(false)
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(conversation.title)
  const root = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (!menu) return
    const close = (event: MouseEvent) => !root.current?.contains(event.target as Node) && setMenu(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menu])

  const rename = async (event: FormEvent) => {
    event.preventDefault()
    setEditing(false)
    if (title.trim() && title.trim() !== conversation.title) {
      await api.renameConversation(conversation.id, title.trim()).catch(() => setTitle(conversation.title))
      onChanged()
    }
  }

  const remove = async () => {
    setMenu(false)
    if (!window.confirm(t('sidebar.confirmDelete'))) return
    await api.deleteConversation(conversation.id).catch(() => undefined)
    onDeleted()
  }

  return (
    <li ref={root} className={`history-item${active ? ' history-item--active' : ''}`}>
      {editing ? (
        <form onSubmit={rename} className="history-item__edit">
          <input value={title} onChange={(e) => setTitle(e.target.value)} autoFocus onBlur={rename} aria-label={t('sidebar.rename')} maxLength={120}
            onKeyDown={(e) => e.key === 'Escape' && (setTitle(conversation.title), setEditing(false))} />
          <button type="submit" className="icon-btn icon-btn--sm" aria-label={t('common.save')}><Check size={14} /></button>
        </form>
      ) : (
        <>
          <button type="button" className="history-item__open" onClick={onOpen} aria-current={active ? 'page' : undefined} title={conversation.title}>
            {conversation.title}
          </button>
          <button type="button" className="icon-btn icon-btn--sm history-item__more" aria-label={t('sidebar.more')} aria-expanded={menu} onClick={() => setMenu(!menu)}>
            <MoreHorizontal size={16} />
          </button>
          {menu && (
            <div className="menu" role="menu">
              <button type="button" role="menuitem" onClick={() => { setMenu(false); setEditing(true) }}><Pencil size={14} aria-hidden /> {t('sidebar.rename')}</button>
              <button type="button" role="menuitem" className="danger" onClick={remove}><Trash2 size={14} aria-hidden /> {t('sidebar.delete')}</button>
            </div>
          )}
        </>
      )}
    </li>
  )
}

function UserMenu() {
  const { t, locale, setLocale } = useT()
  const { role, login, logout, theme, setTheme, settings } = useApp()
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !root.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      await login(password)
      setPassword('')
      setOpen(false)
    } catch (err) {
      setError(err instanceof ApiError && err.kind === 'unauthorized' ? err.message : t('errors.network'))
    }
  }

  const themes: { value: Theme; icon: typeof Sun; label: StringKey }[] = [
    { value: 'light', icon: Sun, label: 'theme.light' }, { value: 'dark', icon: Moon, label: 'theme.dark' }, { value: 'system', icon: SunMoon, label: 'theme.system' },
  ]

  return (
    <div className="user-menu" ref={root}>
      {open && (
        <div className="menu menu--up" role="dialog" aria-label={t('user.theme')}>
          <p className="menu__label">{t('user.theme')}</p>
          <div className="segmented" role="radiogroup" aria-label={t('user.theme')}>
            {themes.map(({ value, icon: Icon, label }) => (
              <button key={value} type="button" role="radio" aria-checked={theme === value} onClick={() => setTheme(value)} title={t(label)}>
                <Icon size={16} aria-hidden /> <span>{t(label)}</span>
              </button>
            ))}
          </div>
          <p className="menu__label">{t('user.language')}</p>
          <div className="segmented" role="radiogroup" aria-label={t('user.language')}>
            {(Object.keys(locales) as Locale[]).map((code) => (
              <button key={code} type="button" role="radio" aria-checked={locale === code} onClick={() => setLocale(code)}>{locales[code].label}</button>
            ))}
          </div>
          <hr />
          {role === 'admin' ? (
            <button type="button" className="menu__item" onClick={() => { logout(); setOpen(false) }}><LogOut size={16} aria-hidden /> {t('user.logout')}</button>
          ) : settings && !settings.admin_enabled ? (
            <p className="muted small">{t('user.loginDisabled')}</p>
          ) : (
            <form onSubmit={submit} className="login-form">
              <label className="field">
                <span className="field__label">{t('user.password')}</span>
                <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
              </label>
              {error && <p className="error-text" role="alert">{error}</p>}
              <button type="submit" className="btn btn--primary" disabled={!password}><LogIn size={16} aria-hidden /> {t('user.loginAction')}</button>
            </form>
          )}
        </div>
      )}
      <button type="button" className="user-menu__button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden>{role === 'admin' ? 'A' : 'É'}</span>
        <span className="user-menu__text">
          <span>{role === 'admin' ? t('user.admin') : t('user.student')}</span>
          <span className="muted small">{t('app.school')}</span>
        </span>
      </button>
    </div>
  )
}

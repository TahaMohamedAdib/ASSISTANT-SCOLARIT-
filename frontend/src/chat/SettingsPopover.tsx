import { SlidersHorizontal } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { appConfig } from '../config'
import { useT } from '../i18n'
import { useApp } from '../state'

/** Reglages avances, replies par defaut : nombre de sources, filtre de type, mode transparence. */
export function SettingsPopover() {
  const { t } = useT()
  const { chat, setChat, docTypes } = useApp()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const id = useId()

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

  return (
    <div className="popover-root" ref={root}>
      <button type="button" className="icon-btn" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} aria-label={t('settings.title')} title={t('settings.title')}>
        <SlidersHorizontal size={18} />
      </button>
      {open && (
        <div className="popover" id={id} role="dialog" aria-label={t('settings.title')}>
          <h2 className="popover__title">{t('settings.title')}</h2>
          <label className="field">
            <span className="field__label">{t('settings.topK')} <output>{chat.topK}</output></span>
            <input type="range" min={appConfig.topK.min} max={appConfig.topK.max} value={chat.topK} onChange={(e) => setChat({ topK: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span className="field__label">{t('settings.docType')}</span>
            <select value={chat.docType ?? ''} onChange={(e) => setChat({ docType: e.target.value || null })}>
              <option value="">{t('settings.allTypes')}</option>
              {docTypes.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
          <label className="switch">
            <input type="checkbox" checked={chat.transparency} onChange={(e) => setChat({ transparency: e.target.checked })} />
            <span>
              <span className="field__label">{t('settings.transparency')}</span>
              <span className="muted small">{t('settings.transparencyHint')}</span>
            </span>
          </label>
        </div>
      )}
    </div>
  )
}

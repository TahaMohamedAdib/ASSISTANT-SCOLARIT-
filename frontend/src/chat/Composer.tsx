import { ArrowUp, Paperclip, Square, X } from 'lucide-react'
import { forwardRef, useImperativeHandle, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { useT } from '../i18n'

export type ComposerHandle = { focus: () => void; setText: (text: string) => void }

type Props = {
  busy: boolean
  disabled?: boolean
  onSend: (text: string) => void
  onStop: () => void
  onAttach?: (file: File) => void
  attachment?: { name: string; uploading: boolean; error?: string } | null
  onRemoveAttachment?: () => void
  accept?: string
}

export const Composer = forwardRef<ComposerHandle, Props>(function Composer(
  { busy, disabled, onSend, onStop, onAttach, attachment, onRemoveAttachment, accept }, ref,
) {
  const { t } = useT()
  const [text, setText] = useState('')
  const area = useRef<HTMLTextAreaElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useImperativeHandle(ref, () => ({
    focus: () => area.current?.focus(),
    setText: (value: string) => {
      setText(value)
      requestAnimationFrame(() => {
        area.current?.focus()
        area.current?.setSelectionRange(value.length, value.length)
      })
    },
  }))

  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`
  }, [text])

  const submit = () => {
    const value = text.trim()
    if (!value || busy || disabled) return
    onSend(value)
    setText('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="composer" onSubmit={(e) => { e.preventDefault(); submit() }}>
      {attachment && (
        <div className="composer__attachment">
          <Paperclip size={14} aria-hidden />
          <span>{attachment.uploading ? t('common.loading') : t('chat.attached', { name: attachment.name })}</span>
          {attachment.error && <span className="composer__attachment-error" role="alert">{attachment.error}</span>}
          <button type="button" className="icon-btn icon-btn--sm" onClick={onRemoveAttachment} aria-label={t('chat.removeAttachment')}><X size={14} /></button>
        </div>
      )}
      <label htmlFor="composer-input" className="sr-only">{t('chat.placeholder')}</label>
      <textarea
        id="composer-input"
        ref={area}
        rows={1}
        value={text}
        maxLength={4000}
        placeholder={t('chat.placeholder')}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled}
      />
      <div className="composer__bar">
        {onAttach && (
          <>
            <input ref={fileInput} type="file" hidden accept={accept} onChange={(e) => { const file = e.target.files?.[0]; if (file) onAttach(file); e.target.value = '' }} />
            <button type="button" className="icon-btn" onClick={() => fileInput.current?.click()} aria-label={t('chat.attach')} title={t('chat.attach')} disabled={busy || disabled}>
              <Paperclip size={18} />
            </button>
          </>
        )}
        <span className="composer__spacer" />
        {busy ? (
          <button type="button" className="send-btn send-btn--stop" onClick={onStop} aria-label={t('chat.stop')} title={t('chat.stop')}>
            <Square size={14} fill="currentColor" />
          </button>
        ) : (
          <button type="submit" className="send-btn" disabled={!text.trim() || disabled} aria-label={t('chat.send')} title={t('chat.send')}>
            <ArrowUp size={18} />
          </button>
        )}
      </div>
    </form>
  )
})

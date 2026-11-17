import type { ReactNode } from 'react'
import { motion } from 'framer-motion'
import { CircleAlert, CircleCheck, Info, LoaderCircle } from 'lucide-react'

const icons = { error: CircleAlert, success: CircleCheck, info: Info }

export function Notice({ tone, children, loading = false }: {
  tone: keyof typeof icons
  children: ReactNode
  loading?: boolean
}) {
  const Icon = loading ? LoaderCircle : icons[tone]

  return (
    <motion.div
      className={`alert alert--${tone}`}
      role={tone === 'error' ? 'alert' : 'status'}
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
    >
      <Icon aria-hidden="true" className={loading ? 'spin' : undefined} size={18} />
      <div>{children}</div>
    </motion.div>
  )
}

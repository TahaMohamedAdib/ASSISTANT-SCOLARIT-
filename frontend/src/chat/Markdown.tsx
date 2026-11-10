import { useMemo, useRef } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** Transforme les marqueurs de citation [1], [1, 3] ou [1][2] en liens internes #cite-n. */
export function linkCitations(text: string) {
  // Certains modeles ecrivent 【1】 ou 【1†source】 : on les ramene a [1] (deja fait cote serveur a la fin du flux).
  return text.replace(/[【〔［]\s*(\d+)(?:\s*†[^】〕］]*)?\s*[】〕］]/g, '[$1]').replace(/\[(\d+(?:\s*[,;]\s*\d+)*)\](?!\()/g, (_, group: string) =>
    group.split(/\s*[,;]\s*/).map((n) => `[${n}](#cite-${n})`).join(''),
  )
}

type Props = { text: string; onCite?: (n: number) => void; validCitations?: Set<number> }

const plugins = [remarkGfm]

export function Markdown({ text, onCite, validCitations }: Props) {
  // Les rendus personnalises doivent rester les memes d'un rendu a l'autre : sinon React
  // remonte les boutons de citation a chaque rafraichissement (clic perdu, focus perdu).
  const latest = useRef({ onCite, validCitations })
  latest.current = { onCite, validCitations }

  const components = useMemo<Components>(() => ({
    a: ({ href, children }) => {
      const match = href?.match(/^#cite-(\d+)$/)
      if (match) {
        const n = Number(match[1])
        const valid = latest.current.validCitations
        if (valid && !valid.has(n)) return <span className="cite cite--invalid">{n}</span>
        return (
          <button type="button" className="cite" onClick={() => latest.current.onCite?.(n)} aria-label={`Source ${n}`}>
            {n}
          </button>
        )
      }
      // Liens externes eventuels : jamais d'ouverture dans le meme onglet ni de referer.
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
    table: ({ children }) => <div className="table-scroll"><table>{children}</table></div>,
  }), [])

  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={plugins} skipHtml components={components}>
        {linkCitations(text)}
      </ReactMarkdown>
    </div>
  )
}

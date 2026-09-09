import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Code2, Eye } from 'lucide-react'

import { cn } from '#/lib/cn'

import type { MarkdownChunk } from '../library.schema'

const PAGE_ANCHOR_RE = /<!--\s*ocr:page:(\d+)\s*-->/

/**
 * Splits the document markdown on page anchors into ordered chunks.
 * Returns null when the file has no anchors (sync unavailable).
 */
export function splitByAnchors(markdown: string): MarkdownChunk[] | null {
  if (!PAGE_ANCHOR_RE.test(markdown)) return null
  // Collect anchors via a replace callback: callback params are typed
  // string/number, avoiding indexed access on the matches array.
  const anchors: { page: number; at: number; after: number }[] = []
  markdown.replace(
    new RegExp(PAGE_ANCHOR_RE.source, 'g'),
    (full, pageStr: string, offset: number) => {
      anchors.push({
        page: Number(pageStr),
        at: offset,
        after: offset + full.length,
      })
      return full
    },
  )
  const chunks: MarkdownChunk[] = []
  anchors.forEach((anchor, index) => {
    const next = anchors[index + 1]
    const end = next === undefined ? markdown.length : next.at
    const content = markdown.slice(anchor.after, end).trim()
    if (anchor.page > 0 && content.length > 0) {
      chunks.push({ page: anchor.page, content })
    }
  })
  return chunks
}

type ChunkViewProps = {
  chunk: MarkdownChunk
  rendered: boolean
  registerRef: (page: number, el: HTMLDivElement | null) => void
}

function ChunkView({
  chunk,
  rendered,
  registerRef,
}: ChunkViewProps): React.JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    registerRef(chunk.page, ref.current)
    return () => registerRef(chunk.page, null)
  }, [chunk.page, registerRef])
  return (
    <div ref={ref} data-page={chunk.page} className="mb-6">
      {rendered ? (
        <div className="markdown-body prose-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {chunk.content}
          </ReactMarkdown>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap rounded-md bg-muted/60 p-3 font-mono text-xs leading-relaxed">
          {chunk.content}
        </pre>
      )}
    </div>
  )
}

type MarkdownPaneProps = {
  markdown: string | null
  currentPage: number
  syncEnabled: boolean
  emptyHint: string
}

/** Right pane: markdown chunks keyed by page anchors, with scroll sync. */
export function MarkdownPane({
  markdown,
  currentPage,
  syncEnabled,
  emptyHint,
}: MarkdownPaneProps): React.JSX.Element {
  const [mode, setMode] = useState<'rendered' | 'source'>('rendered')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const chunkRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const [activePage, setActivePage] = useState<number | null>(null)

  const chunks = useMemo(
    () => (markdown === null ? null : splitByAnchors(markdown)),
    [markdown],
  )
  const hasAnchors = chunks !== null

  // PDF -> markdown: scroll the active page's chunk into view.
  useEffect(() => {
    if (!syncEnabled || !hasAnchors || currentPage <= 0) return
    const el = chunkRefs.current.get(currentPage)
    if (el === undefined) return
    el.scrollIntoView({ block: 'start', behavior: 'smooth' })
    setActivePage(currentPage)
  }, [currentPage, syncEnabled, hasAnchors, markdown])

  const registerRef = useCallback((page: number, el: HTMLDivElement | null) => {
    if (el === null) {
      chunkRefs.current.delete(page)
    } else {
      chunkRefs.current.set(page, el)
    }
  }, [])

  if (markdown === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">
        {emptyHint}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col" data-testid="markdown-pane">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
        <button
          type="button"
          onClick={() => setMode('rendered')}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
            mode === 'rendered'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted',
          )}
          aria-pressed={mode === 'rendered'}
        >
          <Eye className="size-3.5" aria-hidden />
          Rendered
        </button>
        <button
          type="button"
          onClick={() => setMode('source')}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium',
            mode === 'source'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted',
          )}
          aria-pressed={mode === 'source'}
        >
          <Code2 className="size-3.5" aria-hidden />
          Source
        </button>
        {!hasAnchors ? (
          <span className="ml-auto text-xs text-muted-foreground">
            no page anchors — page sync off
          </span>
        ) : (
          <span className="ml-auto text-xs tabular-nums text-muted-foreground">
            {chunks.length} pages
          </span>
        )}
      </div>
      <div ref={scrollRef} className="flex-1 overflow-auto px-5 py-4">
        {hasAnchors ? (
          chunks.map((chunk) => (
            <div
              key={chunk.page}
              className={cn(
                'rounded-lg transition-colors',
                syncEnabled &&
                  activePage === chunk.page &&
                  'bg-primary/5 ring-1 ring-primary/30',
              )}
            >
              <ChunkView
                chunk={chunk}
                rendered={mode === 'rendered'}
                registerRef={registerRef}
              />
            </div>
          ))
        ) : (
          <div className={cn(mode !== 'rendered' && 'font-mono text-xs')}>
            {mode === 'rendered' ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {markdown}
              </ReactMarkdown>
            ) : (
              <pre className="whitespace-pre-wrap rounded-md bg-muted/60 p-3 font-mono text-xs leading-relaxed">
                {markdown}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

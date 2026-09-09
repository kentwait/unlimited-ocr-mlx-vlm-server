import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Code2, Eye } from 'lucide-react'

import { cn } from '#/lib/cn'

import type { FocusSpan, MarkdownChunk } from '../library.schema'

const PAGE_ANCHOR_RE = /<!--\s*ocr:page:(\d+)\s*-->/

/** Normalizes text for fuzzy matching (case/whitespace-insensitive). */
export function normalizeSnippetText(value: string | null | undefined): string {
  if (value === null || value === undefined) return ''
  return value.toLowerCase().replace(/\s+/g, ' ').trim()
}

/**
 * Finds the first block whose normalized text contains a long prefix of the
 * normalized snippet. Tries 64/48/32-char probes so checker rewrites still
 * match; returns -1 when the snippet is too short or nothing matches.
 */
export function findSnippetBlock(
  blockTexts: string[],
  snippet: string,
): number {
  const needle = normalizeSnippetText(snippet)
  if (needle.length < 16) return -1
  const probes = [64, 48, 32]
    .filter((len) => needle.length >= len)
    .map((len) => needle.slice(0, len))
  const candidates = probes.length > 0 ? probes : [needle]
  for (const probe of candidates) {
    const idx = blockTexts.findIndex((text) =>
      normalizeSnippetText(text).includes(probe),
    )
    if (idx !== -1) return idx
  }
  return -1
}

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
        <div className="markdown-body prose prose-sm max-w-none dark:prose-invert">
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
  /** Markdown -> PDF: clicking a page chunk jumps the preview to that page. */
  onChunkClick?: (page: number) => void
  /**
   * Bumped only by PDF-originated page changes. The pane scrolls to the
   * current page on token change — never on markdown-driven changes, so
   * manual scrolling is never yanked.
   */
  scrollToken: number
  /** Section-level focus from overlay clicks (span text snippet). */
  focusSpan?: FocusSpan | null
  /** Markdown -> PDF: the most-visible chunk's page while scrolling. */
  onVisiblePage?: (page: number) => void
  emptyHint: string
}

/** Right pane: markdown chunks keyed by page anchors, with scroll sync. */
export function MarkdownPane({
  markdown,
  currentPage,
  syncEnabled,
  onChunkClick,
  scrollToken,
  focusSpan,
  onVisiblePage,
  emptyHint,
}: MarkdownPaneProps): React.JSX.Element {
  const [mode, setMode] = useState<'rendered' | 'source'>('rendered')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const chunkRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const [activePage, setActivePage] = useState<number | null>(null)
  // Effect below reads the page for scrollToken-driven scrolling through a
  // ref so observer-driven page changes don't re-trigger the scroll.
  const pageForScroll = useRef(currentPage)
  pageForScroll.current = currentPage
  const visibleRef = useRef(onVisiblePage)
  visibleRef.current = onVisiblePage

  const chunks = useMemo(
    () => (markdown === null ? null : splitByAnchors(markdown)),
    [markdown],
  )
  const hasAnchors = chunks !== null

  // PDF -> markdown: scroll the active page's chunk into view. Runs only on
  // scrollToken (PDF-originated) changes, plus sync/markdown toggles.
  useEffect(() => {
    if (!syncEnabled || !hasAnchors) return
    const page = pageForScroll.current
    if (page <= 0) return
    const el = chunkRefs.current.get(page)
    if (el === undefined) return
    el.scrollIntoView({ block: 'start', behavior: 'smooth' })
    setActivePage(page)
  }, [scrollToken, syncEnabled, hasAnchors, markdown])

  // Markdown -> PDF: report the most-visible chunk while scrolling.
  useEffect(() => {
    const root = scrollRef.current
    if (
      !syncEnabled ||
      root === null ||
      chunks === null ||
      typeof IntersectionObserver === 'undefined'
    ) {
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        let best: { page: number; ratio: number } | null = null
        for (const entry of entries) {
          const page = Number(entry.target.getAttribute('data-page'))
          if (
            entry.isIntersecting &&
            Number.isFinite(page) &&
            (best === null || entry.intersectionRatio > best.ratio)
          ) {
            best = { page, ratio: entry.intersectionRatio }
          }
        }
        if (best !== null) visibleRef.current?.(best.page)
      },
      { root, threshold: [0.25, 0.5, 0.75] },
    )
    for (const el of chunkRefs.current.values()) observer.observe(el)
    return () => observer.disconnect()
  }, [chunks, syncEnabled])

  // Overlay -> markdown: scroll to the block matching the span snippet,
  // flash it, fall back to the chunk top when nothing matches.
  useEffect(() => {
    if (focusSpan === null || focusSpan === undefined || !hasAnchors) return
    const chunkEl = chunkRefs.current.get(focusSpan.page)
    if (chunkEl === undefined) return
    const blocks = [
      ...chunkEl.querySelectorAll('p, li, h1, h2, h3, h4, blockquote, td, pre'),
    ]
    const idx = findSnippetBlock(
      blocks.map((b) => normalizeSnippetText(b.textContent)),
      focusSpan.snippet,
    )
    const found = idx !== -1 ? blocks[idx] : undefined
    const target: HTMLElement = found instanceof HTMLElement ? found : chunkEl
    target.scrollIntoView({ block: 'center', behavior: 'smooth' })
    setActivePage(focusSpan.page)
    if (typeof target.animate === 'function') {
      target.animate(
        [
          { boxShadow: '0 0 0 2px var(--ring)' },
          { boxShadow: '0 0 0 0 transparent' },
        ],
        { duration: 1400 },
      )
    }
  }, [focusSpan, hasAnchors, markdown])

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
              role={
                syncEnabled && onChunkClick !== undefined ? 'button' : undefined
              }
              tabIndex={
                syncEnabled && onChunkClick !== undefined ? 0 : undefined
              }
              aria-label={
                syncEnabled && onChunkClick !== undefined
                  ? `Show PDF page ${String(chunk.page)}`
                  : undefined
              }
              onClick={
                syncEnabled && onChunkClick !== undefined
                  ? () => onChunkClick(chunk.page)
                  : undefined
              }
              onKeyDown={
                syncEnabled && onChunkClick !== undefined
                  ? (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onChunkClick(chunk.page)
                      }
                    }
                  : undefined
              }
              className={cn(
                'rounded-lg transition-colors',
                syncEnabled &&
                  activePage === chunk.page &&
                  'bg-primary/5 ring-1 ring-primary/30',
                syncEnabled &&
                  onChunkClick !== undefined &&
                  'cursor-pointer hover:bg-muted/60',
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
          <div
            className={cn(
              mode !== 'rendered' && 'font-mono text-xs',
              mode === 'rendered' &&
                'prose prose-sm max-w-none dark:prose-invert',
            )}
          >
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

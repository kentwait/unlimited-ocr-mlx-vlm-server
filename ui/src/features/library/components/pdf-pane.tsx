import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'

import { Button } from '#/shared/components/ui/button'
import { debugFs, pickReadingPage, readPdfBytes } from '../library.functions'
import { scrollChildIntoView } from '../scroll'
import type { Span, TreeNode } from '../library.schema'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

type OverlayRect = {
  x: number
  y: number
  w: number
  h: number
  label: string
}

type PdfPaneProps = {
  pdfNode: TreeNode
  currentPage: number
  /** Scroll tracking reports (page anchor): moves state only, never scrolls. */
  onTrackPage: (page: number) => void
  /** Pager/keyboard jumps: parent bumps scrollToken so the list scrolls. */
  onJumpPage: (page: number) => void
  /** Bumped only by externally-originated jumps (pager, chunk clicks). */
  scrollToken: number
  spansByPage: Map<number, Span[]> | null
  syncEnabled: boolean
  /** Overlay -> markdown: clicking a span box jumps to its section. */
  onSpanClick: ((span: Span) => void) | undefined
}

type PageCanvasProps = {
  doc: pdfjs.PDFDocumentProxy
  pageNum: number
  wrapWidth: number
  spans: Span[] | null
  syncEnabled: boolean
  onSpanClick: ((span: Span) => void) | undefined
  registerEl: (page: number, el: HTMLDivElement | null) => void
  onRenderError: (message: string) => void
}

/** One page: canvas rendered lazily when scrolled near, plus span overlay. */
function PageCanvas({
  doc,
  pageNum,
  wrapWidth,
  spans,
  syncEnabled,
  onSpanClick,
  registerEl,
  onRenderError,
}: PageCanvasProps): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapEl = useRef<HTMLDivElement | null>(null)
  const [ready, setReady] = useState(false)

  // Size the canvas from page metadata, then paint pixels when visible.
  useEffect(() => {
    // Holder (not a plain boolean): TS narrows locals across awaits, which
    // would make the cancellation checks look "always truthy" to the linter.
    // Reads go through a closure for the same reason.
    const alive = { current: true }
    const isAlive = (): boolean => alive.current
    const el = wrapEl.current
    if (el === null) return undefined
    registerEl(pageNum, el)

    async function render(): Promise<void> {
      try {
        const page = await doc.getPage(pageNum)
        if (!isAlive()) return
        const canvas = canvasRef.current
        if (canvas === null) return
        const base = page.getViewport({ scale: 1 })
        const scale = Math.max(0.3, (wrapWidth - 24) / base.width)
        const viewport = page.getViewport({ scale })
        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)
        const ctx = canvas.getContext('2d')
        if (ctx === null) return
        await page.render({ canvas, canvasContext: ctx, viewport }).promise
        if (isAlive()) setReady(true)
      } catch (cause: unknown) {
        // No alive check here: reporting into unmounted state is a
        // harmless no-op in React 18+, and narrowing would flag the check.
        onRenderError(cause instanceof Error ? cause.message : String(cause))
      }
    }

    if (typeof IntersectionObserver === 'undefined') {
      void render()
    } else {
      const observer = new IntersectionObserver(
        (entries) => {
          if (entries.some((entry) => entry.isIntersecting)) {
            observer.disconnect()
            void render()
          }
        },
        { rootMargin: '800px' },
      )
      observer.observe(el)
      return () => observer.disconnect()
    }
    return () => {
      alive.current = false
      registerEl(pageNum, null)
    }
  }, [doc, pageNum, wrapWidth])

  const rects: OverlayRect[] = useMemo(() => {
    if (spans === null) return []
    return spans.map((span) => ({
      x: (span.box[0] ?? 0) / 1000,
      y: (span.box[1] ?? 0) / 1000,
      w: ((span.box[2] ?? 0) - (span.box[0] ?? 0)) / 1000,
      h: ((span.box[3] ?? 0) - (span.box[1] ?? 0)) / 1000,
      label: span.label,
    }))
  }, [spans])

  return (
    <div
      ref={wrapEl}
      data-page={pageNum}
      className="relative mx-auto my-3 w-fit"
    >
      {!ready ? (
        <div
          aria-hidden
          className="flex h-96 w-[640px] max-w-full animate-pulse items-center justify-center rounded bg-muted/60 text-xs text-muted-foreground"
        >
          page {pageNum}…
        </div>
      ) : null}
      <canvas
        ref={canvasRef}
        className="block shadow-md"
        aria-label={`PDF page ${String(pageNum)} preview`}
      />
      {syncEnabled && ready
        ? rects.map((rect, index) => {
            const span = spans?.[index]
            const clickable = onSpanClick !== undefined && span !== undefined
            return (
              <button
                key={index}
                type="button"
                disabled={!clickable}
                title={
                  span !== undefined
                    ? `${rect.label}: ${span.text.slice(0, 120)}`
                    : rect.label
                }
                aria-label={
                  clickable
                    ? `Show markdown for ${rect.label}: ${span.text.slice(0, 80)}`
                    : rect.label
                }
                onClick={clickable ? () => onSpanClick(span) : undefined}
                className="absolute rounded-[2px] border border-primary/50 bg-primary/10 transition-colors hover:border-primary hover:bg-primary/25 disabled:cursor-default disabled:hover:border-primary/50 disabled:hover:bg-primary/10 enabled:cursor-pointer"
                style={{
                  left: `${String(rect.x * 100)}%`,
                  top: `${String(rect.y * 100)}%`,
                  width: `${String(rect.w * 100)}%`,
                  height: `${String(rect.h * 100)}%`,
                }}
              />
            )
          })
        : null}
    </div>
  )
}

/** Middle pane: continuously scrolling PDF with per-page span overlays. */
export function PdfPane({
  pdfNode,
  currentPage,
  onTrackPage,
  onJumpPage,
  scrollToken,
  spansByPage,
  syncEnabled,
  onSpanClick,
}: PdfPaneProps): React.JSX.Element {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const pageEls = useRef<Map<number, HTMLDivElement>>(new Map())
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [numPages, setNumPages] = useState(0)
  const [wrapWidth, setWrapWidth] = useState(720)
  const pageForScroll = useRef(currentPage)
  pageForScroll.current = currentPage
  const trackRef = useRef(onTrackPage)
  trackRef.current = onTrackPage
  const jumpRef = useRef(onJumpPage)
  jumpRef.current = onJumpPage
  // Suppression window: while a jump scroll is in flight, scroll tracking
  // stays quiet so the list can't chase its own programmatic scroll.
  const followGuard = useRef(false)
  const guardTimer = useRef<number | null>(null)
  useEffect(() => {
    const timer = guardTimer.current
    return () => {
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [])

  function suppressFollow(ms: number): void {
    followGuard.current = true
    if (guardTimer.current !== null) window.clearTimeout(guardTimer.current)
    guardTimer.current = window.setTimeout(() => {
      followGuard.current = false
    }, ms)
  }

  // Load the document once per file. Bytes come through the fs plugin
  // (scope granted in the Rust set_root command), bypassing the asset
  // protocol fetch that WebKit rejects with a bare "Load failed".
  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setLoadError(null)
    setNumPages(0)
    pageEls.current.clear()
    let task: pdfjs.PDFDocumentLoadingTask | null = null
    readPdfBytes(pdfNode.path)
      .then((data) => {
        if (cancelled) return undefined
        task = pdfjs.getDocument({ data })
        return task.promise
      })
      .then((loaded) => {
        if (loaded === undefined) return
        if (cancelled) {
          void task?.destroy()
          return
        }
        setDoc(loaded)
        setNumPages(loaded.numPages)
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          // WebKit reports asset-protocol blocks as a bare TypeError
          // ("Load failed") with no status: name the stage so the next
          // failure is diagnosable (scope vs. missing file vs. bad PDF).
          const detail = cause instanceof Error ? cause.message : String(cause)
          const stage =
            detail.includes('fetch failed') || detail === 'Load failed'
              ? 'file fetch (library-root scope or missing file)'
              : 'PDF parse'
          setLoadError(`${stage}: ${detail}`)
          // Annotate with the definitive scope verdict from the Rust layer.
          void debugFs(pdfNode.path)
            .then((d) => {
              if (cancelled || d === null) return
              const verdict =
                d.allowed || d.allowedCanonical ? 'scope OK' : 'scope DENIED'
              const canon =
                d.canonicalPath !== null && d.canonicalPath !== d.path
                  ? ` canon=${d.canonicalPath}`
                  : ''
              setLoadError((prev) =>
                prev === null ? prev : `${prev} [${verdict}${canon}]`,
              )
            })
            .catch(() => {
              // diagnostics are best-effort; the load error above stands
            })
        }
      })
    return () => {
      cancelled = true
      if (task !== null) void task.destroy()
    }
  }, [pdfNode.path])

  // Track the pane width so renders stay fit-to-width on resize.
  useEffect(() => {
    const wrap = wrapRef.current
    if (wrap === null) return
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width
      if (width !== undefined) setWrapWidth(width)
    })
    observer.observe(wrap)
    return () => observer.disconnect()
  }, [])

  const registerEl = useCallback((page: number, el: HTMLDivElement | null) => {
    if (el === null) {
      pageEls.current.delete(page)
    } else {
      pageEls.current.set(page, el)
    }
  }, [])

  const onRenderError = useCallback((message: string) => {
    setRenderError((prev) => prev ?? message)
  }, [])

  // Scroll-driven page tracking (page anchor): the page whose top last
  // crossed the anchor line becomes current. State only — never scrolls.
  // rAF-throttled; quiet during jump scrolls.
  const trackVisible = useCallback(() => {
    const root = wrapRef.current
    if (doc === null || root === null || followGuard.current) return
    const rootTop = root.getBoundingClientRect().top
    const entries: { page: number; top: number }[] = []
    for (const [page, el] of pageEls.current) {
      entries.push({
        page,
        top: el.getBoundingClientRect().top - rootTop,
      })
    }
    const best = pickReadingPage(entries, root.clientHeight * 0.25)
    if (best !== null) trackRef.current(best)
  }, [doc])

  const scrollRaf = useRef(0)
  useEffect(() => {
    const id = scrollRaf.current
    return () => cancelAnimationFrame(id)
  }, [])

  // Externally-originated jumps (pager, chunk clicks, markdown scroll)
  // anchor the page list. Discrete jump + suppression: no feedback loop.
  useEffect(() => {
    if (scrollToken === 0) return
    const el = pageEls.current.get(pageForScroll.current)
    const root = wrapRef.current
    if (el === undefined || root === null) return
    suppressFollow(450)
    scrollChildIntoView(root, el, 'start')
  }, [scrollToken])

  const goPage = useCallback(
    (delta: number) => {
      const next = pageForScroll.current + delta
      if (next >= 1 && next <= numPages) jumpRef.current(next)
    },
    [numPages],
  )

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'ArrowLeft') goPage(-1)
      if (event.key === 'ArrowRight') goPage(1)
    },
    [goPage],
  )

  const pageNums: number[] =
    numPages === 0 ? [] : [...Array(numPages).keys()].map((i) => i + 1)

  return (
    <div className="flex h-full flex-col" data-testid="pdf-pane">
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            aria-label="Previous page"
            disabled={currentPage <= 1}
            onClick={() => goPage(-1)}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </Button>
          <span className="text-xs tabular-nums text-muted-foreground">
            page {numPages === 0 ? '–' : currentPage} / {numPages || '–'}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Next page"
            disabled={currentPage >= numPages}
            onClick={() => goPage(1)}
          >
            <ChevronRight className="size-4" aria-hidden />
          </Button>
          {doc === null && loadError === null ? (
            <Loader2
              className="size-3.5 animate-spin text-muted-foreground"
              aria-hidden
            />
          ) : null}
        </div>
      </div>
      <div
        ref={wrapRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onScroll={() => {
          cancelAnimationFrame(scrollRaf.current)
          scrollRaf.current = requestAnimationFrame(() => trackVisible())
        }}
        className="relative flex-1 overflow-auto bg-muted/40 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        {loadError !== null ? (
          <div
            role="alert"
            className="m-4 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              Cannot open PDF: {loadError}
              {loadError.includes('fetch failed')
                ? ' (library root scope may need re-open)'
                : ''}
            </span>
          </div>
        ) : doc === null ? null : (
          pageNums.map((pageNum) => (
            <PageCanvas
              key={`${pdfNode.path}:${String(pageNum)}`}
              doc={doc}
              pageNum={pageNum}
              wrapWidth={wrapWidth}
              spans={spansByPage?.get(pageNum) ?? null}
              syncEnabled={syncEnabled}
              onSpanClick={onSpanClick}
              registerEl={registerEl}
              onRenderError={onRenderError}
            />
          ))
        )}
        {renderError !== null ? (
          <div role="alert" className="m-4 text-sm text-destructive">
            Render failed: {renderError}
          </div>
        ) : null}
      </div>
    </div>
  )
}

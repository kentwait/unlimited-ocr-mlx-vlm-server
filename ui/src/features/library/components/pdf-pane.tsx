import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { AlertTriangle, ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'

import { Button } from '#/shared/components/ui/button'
import { debugFs, readPdfBytes } from '../library.functions'
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
  onPageChange: (page: number) => void
  spansForPage: Span[] | null
  syncEnabled: boolean
}

type CanvasSize = { width: number; height: number }

/** Middle pane: single-page PDF preview with a span-box overlay. */
export function PdfPane({
  pdfNode,
  currentPage,
  onPageChange,
  spansForPage,
  syncEnabled,
}: PdfPaneProps): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [numPages, setNumPages] = useState(0)
  const [canvasSize, setCanvasSize] = useState<CanvasSize | null>(null)
  const [wrapWidth, setWrapWidth] = useState(720)

  // Load the document once per file. Bytes come through the fs plugin
  // (scope granted in the Rust set_root command), bypassing the asset
  // protocol fetch that WebKit rejects with a bare "Load failed".
  useEffect(() => {
    let cancelled = false
    setDoc(null)
    setLoadError(null)
    setNumPages(0)
    let task: pdfjs.PDFDocumentLoadingTask | null = null
    readPdfBytes(pdfNode.path)
      .then((data) => {
        if (cancelled) return undefined
        task = pdfjs.getDocument({ data })
        return task.promise
      })
      .then((loaded) => {
        if (loaded === undefined) return
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

  // Render the current page whenever document/page/width changes.
  useEffect(() => {
    if (doc === null) return
    let cancelled = false
    setBusy(true)
    setRenderError(null)
    doc
      .getPage(currentPage)
      .then((page) => {
        if (cancelled) return
        const canvas = canvasRef.current
        if (canvas === null) return
        const base = page.getViewport({ scale: 1 })
        const scale = Math.max(0.3, (wrapWidth - 24) / base.width)
        const viewport = page.getViewport({ scale })
        canvas.width = Math.ceil(viewport.width)
        canvas.height = Math.ceil(viewport.height)
        setCanvasSize({ width: canvas.width, height: canvas.height })
        const ctx = canvas.getContext('2d')
        if (ctx === null) return
        return page.render({ canvas, canvasContext: ctx, viewport }).promise
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setRenderError(cause instanceof Error ? cause.message : String(cause))
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(false)
      })
    return () => {
      cancelled = true
    }
  }, [doc, currentPage, wrapWidth])

  const goPage = useCallback(
    (delta: number) => {
      const next = currentPage + delta
      if (next >= 1 && next <= numPages) onPageChange(next)
    },
    [currentPage, numPages, onPageChange],
  )

  // Overlay rects from this page's spans (box normalized 0-1000).
  const rects: OverlayRect[] = useMemo(() => {
    if (spansForPage === null || canvasSize === null) return []
    return spansForPage.map((span) => ({
      x: (span.box[0] ?? 0) / 1000,
      y: (span.box[1] ?? 0) / 1000,
      w: ((span.box[2] ?? 0) - (span.box[0] ?? 0)) / 1000,
      h: ((span.box[3] ?? 0) - (span.box[1] ?? 0)) / 1000,
      label: span.label,
    }))
  }, [spansForPage, canvasSize])

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'ArrowLeft') goPage(-1)
      if (event.key === 'ArrowRight') goPage(1)
    },
    [goPage],
  )

  return (
    <div className="flex h-full flex-col" data-testid="pdf-pane">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
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
        {busy ? (
          <Loader2
            className="size-3.5 animate-spin text-muted-foreground"
            aria-hidden
          />
        ) : null}
      </div>
      <div
        ref={wrapRef}
        tabIndex={0}
        onKeyDown={onKeyDown}
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
        ) : (
          <div className="relative mx-auto my-3 w-fit">
            <canvas
              ref={canvasRef}
              className="block shadow-md"
              aria-label={`PDF page ${String(currentPage)} preview`}
            />
            {syncEnabled
              ? rects.map((rect, index) => (
                  <div
                    key={index}
                    title={rect.label}
                    className="pointer-events-none absolute rounded-[2px] border border-primary/50 bg-primary/10"
                    style={{
                      left: `${String(rect.x * 100)}%`,
                      top: `${String(rect.y * 100)}%`,
                      width: `${String(rect.w * 100)}%`,
                      height: `${String(rect.h * 100)}%`,
                    }}
                  />
                ))
              : null}
          </div>
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

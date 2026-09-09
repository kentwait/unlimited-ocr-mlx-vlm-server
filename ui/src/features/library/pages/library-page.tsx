import { useCallback, useEffect, useRef, useState } from 'react'
import { FolderOpen, RefreshCw } from 'lucide-react'

import { Button } from '#/shared/components/ui/button'
import { cn } from '#/lib/cn'

import {
  getRoot,
  listTree,
  markdownPathFor,
  parseSpansJsonl,
  pickRootFolder,
  readPdfBytes,
  readTextFile,
  setRoot,
  spansPathFor,
  writeTextFile,
} from '../library.functions'
import {
  assembleMarkdown,
  getHealth,
  getOcrBaseUrl,
  pollJobUntilDone,
  submitParseJob,
} from '../library.ocr'
import {
  type FocusSpan,
  type ParseJobStatus,
  type ParseOptions,
  type Span,
  type TreeNode,
} from '../library.schema'
import { LibraryTree } from '../components/library-tree'
import { PaneDivider } from '../components/pane-divider'
import { PdfPane } from '../components/pdf-pane'
import { MarkdownPane } from '../components/markdown-pane'

type JobState = {
  status: ParseJobStatus
  pdfPath: string
}

const MIN_PANE_W = 180
const MAX_PANE_W = 720

function clampPaneWidth(value: number): number {
  return Math.min(MAX_PANE_W, Math.max(MIN_PANE_W, value))
}

/** localStorage-backed pane width (SSR-safe: falls back during prerender). */
function loadPaneWidth(key: string, fallback: number): number {
  try {
    if (typeof window === 'undefined') return fallback
    const raw = window.localStorage.getItem(key)
    const parsed = raw === null ? NaN : Number(raw)
    return Number.isFinite(parsed) ? clampPaneWidth(parsed) : fallback
  } catch {
    return fallback
  }
}

function savePaneWidth(key: string, value: number): void {
  try {
    window.localStorage.setItem(key, String(Math.round(value)))
  } catch {
    // persistence is best-effort; the drag itself already applied
  }
}

/** Full three-pane library UI with toolbar. */
export function LibraryPage(): React.JSX.Element {
  const [root, setRootState] = useState<string | null>(null)
  const [tree, setTreeState] = useState<TreeNode | null>(null)
  const [selected, setSelected] = useState<TreeNode | null>(null)
  const [markdown, setMarkdown] = useState<string | null>(null)
  const [spans, setSpans] = useState<Map<number, Span[]> | null>(null)
  const [syncEnabled, setSyncEnabled] = useState(true)
  const [health, setHealth] = useState<'checking' | 'ok' | 'down'>('checking')
  const [job, setJob] = useState<JobState | null>(null)
  const [jobError, setJobError] = useState<string | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [spansWarning, setSpansWarning] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [focusSpan, setFocusSpan] = useState<FocusSpan | null>(null)
  // Directional follow-tokens: each pane anchors only on ITS token, so a
  // pane never scrolls itself. PDF-track bumps mdToken, markdown-observe
  // bumps pdfToken, explicit jumps bump both.
  const [scrollToken, setScrollToken] = useState(0)
  const [pdfToken, setPdfToken] = useState(0)
  const [leftW, setLeftW] = useState(() => loadPaneWidth('ocr-ui:leftW', 288))
  const [rightW, setRightW] = useState(() =>
    loadPaneWidth('ocr-ui:rightW', 420),
  )
  const [ocrOptions, setOcrOptions] = useState<ParseOptions>({
    dpi: 300,
    pages: 'all',
    furniture: 'auto',
    ocrModel: 'default',
  })
  const [showOptions, setShowOptions] = useState(false)
  const loadedForPath = useRef<string | null>(null)
  // Mirror for the markdown-visible-page callback (avoids stale closures).
  const pageMirror = useRef(currentPage)
  useEffect(() => {
    pageMirror.current = currentPage
  }, [currentPage])

  /** PDF-originated page change: moves preview AND scrolls markdown. */
  const goPdfPage = useCallback((page: number) => {
    setFocusSpan(null)
    setCurrentPage(page)
    setScrollToken((t) => t + 1)
    setPdfToken((t) => t + 1)
  }, [])

  /** Overlay click: focus the matching markdown section (page already set). */
  const handleSpanClick = useCallback((span: Span) => {
    setCurrentPage(span.page)
    setFocusSpan({ page: span.page, snippet: span.text, nonce: Date.now() })
  }, [])

  /** PDF scroll tracking: markdown anchors to the new page. */
  const handlePdfTrack = useCallback((page: number) => {
    if (pageMirror.current !== page) {
      setCurrentPage(page)
      setScrollToken((t) => t + 1)
    }
  }, [])

  /** Markdown scroll position: PDF anchors to the span's page. */
  const handleMdVisible = useCallback(
    (_page: number, span: Span | null) => {
      const page = span?.page ?? _page
      if (pageMirror.current !== page) {
        setCurrentPage(page)
        setPdfToken((t) => t + 1)
      }
    },
    [],
  )

  const loadTree = useCallback(async (rootPath: string) => {
    setTreeError(null)
    try {
      await setRoot(rootPath)
      setRootState(rootPath)
      setTreeState(await listTree())
    } catch (cause: unknown) {
      setTreeError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [])

  // Restore root and poll server health on mount.
  useEffect(() => {
    let cancelled = false
    void getRoot().then((saved) => {
      if (!cancelled && saved !== null) void loadTree(saved)
    })
    const id = window.setInterval(() => {
      void getHealth()
        .then(() => {
          if (!cancelled) setHealth('ok')
        })
        .catch(() => {
          if (!cancelled) setHealth('down')
        })
    }, 5000)
    void getHealth()
      .then(() => setHealth('ok'))
      .catch(() => setHealth('down'))
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [loadTree])

  const refreshTree = useCallback(async () => {
    setTreeError(null)
    try {
      setTreeState(await listTree())
    } catch (cause: unknown) {
      setTreeError(cause instanceof Error ? cause.message : String(cause))
    }
  }, [])

  const openRoot = useCallback(async () => {
    const chosen = await pickRootFolder()
    if (chosen !== null) await loadTree(chosen)
  }, [loadTree])

  // Selection -> load markdown + spans sidecars (once per path).
  const selectNode = useCallback((node: TreeNode) => {
    setSelected(node)
    setCurrentPage(1)
    setFocusSpan(null)
    setMarkdown(null)
    setSpans(null)
    setSpansWarning(null)
    setJobError(null)
    if (node.kind !== 'pdf') return
    if (loadedForPath.current === node.path) return
    loadedForPath.current = node.path
    const mdPath = markdownPathFor(node.path)
    const spansPath = spansPathFor(node.path)
    void readTextFile(mdPath)
      .then((text) => {
        setMarkdown(text)
        return readTextFile(spansPath)
      })
      .then((jsonl) => {
        try {
          setSpans(parseSpansJsonl(jsonl))
        } catch {
          // Markdown stands; overlay goes off with an explanation.
          setSpans(null)
          setSpansWarning('spans sidecar is invalid — overlay off')
        }
      })
      .catch(() => {
        setSpans(null)
      })
  }, [])

  const onJobSettled = useCallback(
    (status: ParseJobStatus, pdfPath: string) => {
      if (
        status.status === 'done' &&
        status.result !== undefined &&
        status.result !== null
      ) {
        const md = assembleMarkdown(status.result.results)
        const spansJsonl = status.result.results
          .map((page) => page.spans_jsonl ?? '')
          .filter((text) => text.length > 0)
          .join('\n')
        try {
          setSpans(parseSpansJsonl(spansJsonl))
          setSpansWarning(null)
        } catch {
          setSpans(null)
          setSpansWarning('server returned invalid spans — overlay off')
        }
        // Allow reselect to reload the just-saved sidecars from disk.
        loadedForPath.current = pdfPath
        void writeTextFile(markdownPathFor(pdfPath), md)
          .then(() => writeTextFile(spansPathFor(pdfPath), spansJsonl))
          .then(() => refreshTree())
        setMarkdown(md)
        setJob(null)
      } else if (status.status === 'error') {
        setJobError(status.error ?? 'unknown error')
        setJob(null)
      }
    },
    [refreshTree],
  )

  const startOcr = useCallback(
    async (node: TreeNode) => {
      if (node.kind !== 'pdf') return
      if (job !== null) {
        setJobError('an OCR job is already running — wait for it to finish')
        return
      }
      setJobError(null)
      try {
        const data = await readPdfBytes(node.path)
        const file = new File([data as BlobPart], node.name, {
          type: 'application/pdf',
        })
        const submitted = await submitParseJob(file, ocrOptions)
        setJob({ status: submitted, pdfPath: node.path })
        const finalStatus = await pollJobUntilDone(
          submitted.job_id,
          (status) => {
            setJob({ status, pdfPath: node.path })
          },
        )
        onJobSettled(finalStatus, node.path)
      } catch (cause: unknown) {
        setJobError(cause instanceof Error ? cause.message : String(cause))
        setJob(null)
      }
    },
    [job, ocrOptions, onJobSettled],
  )

  const busyPdfPath = job?.pdfPath ?? null
  const progress =
    job !== null &&
    typeof job.status.pages_total === 'number' &&
    job.status.pages_total > 0
      ? `${String(job.status.pages_done ?? 0)}/${String(job.status.pages_total)}`
      : null

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Button variant="outline" size="sm" onClick={() => void openRoot()}>
          <FolderOpen className="size-4" aria-hidden />
          Open root…
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Refresh tree"
          onClick={() => void refreshTree()}
        >
          <RefreshCw className="size-4" aria-hidden />
        </Button>
        <span className="ml-2 min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {root ?? 'no folder open'}
        </span>
        {selected?.kind === 'pdf' ? (
          job === null ? (
            <div className="relative inline-flex items-center gap-1">
              <Button size="sm" onClick={() => void startOcr(selected)}>
                {selected.hasMd ? 'Re-run OCR' : 'OCR this PDF'}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label="OCR options"
                aria-expanded={showOptions}
                onClick={() => setShowOptions((v) => !v)}
              >
                ⚙
              </Button>
              {showOptions ? (
                <div className="absolute right-0 top-full z-10 mt-1 w-56 rounded-lg border border-border bg-card p-3 shadow-lg">
                  <label className="mb-2 block text-xs text-muted-foreground">
                    pages
                    <input
                      type="text"
                      value={ocrOptions.pages}
                      onChange={(event) =>
                        setOcrOptions((o) => ({
                          ...o,
                          pages: event.target.value || 'all',
                        }))
                      }
                      placeholder="all | 1-3,5"
                      className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                    />
                  </label>
                  <label className="mb-2 block text-xs text-muted-foreground">
                    dpi
                    <select
                      value={ocrOptions.dpi}
                      onChange={(event) =>
                        setOcrOptions((o) => ({
                          ...o,
                          dpi: Number(event.target.value),
                        }))
                      }
                      className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                    >
                      <option value={150}>150</option>
                      <option value={200}>200</option>
                      <option value={300}>300</option>
                    </select>
                  </label>
                  <label className="mb-2 block text-xs text-muted-foreground">
                    ocr model
                    <select
                      value={ocrOptions.ocrModel}
                      onChange={(event) =>
                        setOcrOptions((o) => ({
                          ...o,
                          ocrModel: event.target
                            .value as ParseOptions['ocrModel'],
                        }))
                      }
                      className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                    >
                      <option value="default">default (mxfp8)</option>
                      <option value="bf16">bf16 (loop-free dense)</option>
                    </select>
                  </label>
                  <label className="block text-xs text-muted-foreground">
                    furniture
                    <select
                      value={ocrOptions.furniture}
                      onChange={(event) =>
                        setOcrOptions((o) => ({
                          ...o,
                          furniture: event.target
                            .value as ParseOptions['furniture'],
                        }))
                      }
                      className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground"
                    >
                      <option value="auto">auto</option>
                      <option value="none">none</option>
                      <option value="nature">nature</option>
                      <option value="science">science</option>
                      <option value="pmc">pmc</option>
                    </select>
                  </label>
                </div>
              ) : null}
            </div>
          ) : (
            <span className="inline-flex items-center gap-2 text-xs text-primary">
              OCR{' '}
              {progress === null
                ? job.status.status
                : `${progress} · ${job.status.phase ?? 'ocr'}`}
            </span>
          )
        ) : (
          <span className="text-xs text-muted-foreground">
            select a PDF to OCR
          </span>
        )}
        {jobError !== null ? (
          <span
            role="alert"
            className="max-w-72 truncate text-xs text-destructive"
          >
            {jobError}
          </span>
        ) : null}
        <label className="ml-2 inline-flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={syncEnabled}
            onChange={(event) => setSyncEnabled(event.target.checked)}
          />
          sync
        </label>
        <span
          role="status"
          aria-label={`OCR server ${getOcrBaseUrl()} ${health === 'ok' ? 'reachable' : 'unreachable'}`}
          title={getOcrBaseUrl()}
          className="ml-2 inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"
        >
          server {getOcrBaseUrl()} ·{' '}
          {health === 'ok' ? (
            <span className="font-medium text-primary">connected</span>
          ) : health === 'checking' ? (
            <span>connecting…</span>
          ) : (
            <span className="font-medium text-destructive">unreachable</span>
          )}
          <span
            aria-hidden
            className={cn(
              'size-2 rounded-full',
              health === 'ok'
                ? 'bg-primary'
                : health === 'checking'
                  ? 'bg-muted-foreground/40'
                  : 'bg-destructive',
            )}
          />
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside
          className="shrink-0 overflow-auto border-r border-border"
          style={{ width: `${String(leftW)}px` }}
        >
          {treeError !== null ? (
            <div
              role="alert"
              className="m-3 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive"
            >
              Library read failed: {treeError}
            </div>
          ) : null}
          {tree === null ? (
            <div className="p-3">
              <p className="mb-3 text-sm text-muted-foreground">
                No folder open.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void openRoot()}
              >
                <FolderOpen className="size-4" aria-hidden />
                Open root…
              </Button>
            </div>
          ) : (
            <LibraryTree
              tree={tree}
              selectedPath={selected?.path ?? null}
              onSelect={selectNode}
              busyPdfPath={busyPdfPath}
            />
          )}
        </aside>
        <PaneDivider
          label="Resize library tree"
          onDrag={(dx) =>
            setLeftW((w) => {
              const next = clampPaneWidth(w + dx)
              savePaneWidth('ocr-ui:leftW', next)
              return next
            })
          }
        />
        <section className="flex min-w-0 flex-1 flex-col border-r border-border">
          {selected?.kind === 'pdf' ? (
            <PdfPane
              pdfNode={selected}
              currentPage={currentPage}
              onTrackPage={handlePdfTrack}
              onJumpPage={goPdfPage}
              scrollToken={pdfToken}
              spansByPage={spans}
              syncEnabled={syncEnabled}
              onSpanClick={handleSpanClick}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground">
              Select a PDF in the tree to preview it.
            </div>
          )}
        </section>
        <PaneDivider
          label="Resize markdown pane"
          onDrag={(dx) =>
            setRightW((w) => {
              const next = clampPaneWidth(w - dx)
              savePaneWidth('ocr-ui:rightW', next)
              return next
            })
          }
        />
        <section
          className="flex shrink-0 flex-col"
          style={{ width: `${String(rightW)}px` }}
        >
          <MarkdownPane
            markdown={markdown}
            currentPage={currentPage}
            syncEnabled={syncEnabled}
            onChunkClick={goPdfPage}
            scrollToken={scrollToken}
            focusSpan={focusSpan}
            onVisiblePage={handleMdVisible}
            onJumpPage={goPdfPage}
            spansByPage={spans}
            emptyHint={
              selected === null
                ? 'Select a PDF to see its markdown.'
                : job !== null
                  ? 'OCR running — markdown will appear when done.'
                  : 'No markdown sidecar for this PDF yet. Run OCR.'
            }
          />
          <div className="border-t border-border px-3 py-1.5 text-xs text-muted-foreground">
            {spansWarning !== null ? (
              <span className="text-amber-600 dark:text-amber-400">
                {spansWarning}
              </span>
            ) : selected?.kind === 'pdf' && selected.hasMd ? (
              `saved: ${markdownPathFor(selected.path)}`
            ) : (
              'no sidecar'
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

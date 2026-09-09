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
  pollJobUntilDone,
  submitParseJob,
} from '../library.ocr'
import {
  type ParseJobStatus,
  type ParseOptions,
  type Span,
  type TreeNode,
} from '../library.schema'
import { LibraryTree } from '../components/library-tree'
import { PdfPane } from '../components/pdf-pane'
import { MarkdownPane } from '../components/markdown-pane'

type JobState = {
  status: ParseJobStatus
  pdfPath: string
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
  const [ocrOptions, setOcrOptions] = useState<ParseOptions>({
    dpi: 300,
    pages: 'all',
    furniture: 'auto',
    ocrModel: 'default',
  })
  const [showOptions, setShowOptions] = useState(false)
  const loadedForPath = useRef<string | null>(null)

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
          aria-label={
            health === 'ok' ? 'OCR server reachable' : 'OCR server unreachable'
          }
          className={cn(
            'size-2 rounded-full',
            health === 'ok'
              ? 'bg-primary'
              : health === 'checking'
                ? 'bg-muted-foreground/40'
                : 'bg-destructive',
          )}
        />
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-72 shrink-0 overflow-auto border-r border-border">
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
        <section className="flex min-w-0 flex-1 flex-col border-r border-border">
          {selected?.kind === 'pdf' ? (
            <PdfPane
              pdfNode={selected}
              currentPage={currentPage}
              onPageChange={setCurrentPage}
              spansForPage={spans?.get(currentPage) ?? null}
              syncEnabled={syncEnabled}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground">
              Select a PDF in the tree to preview it.
            </div>
          )}
        </section>
        <section className="flex w-[420px] shrink-0 flex-col">
          <MarkdownPane
            markdown={markdown}
            currentPage={currentPage}
            syncEnabled={syncEnabled}
            onChunkClick={setCurrentPage}
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

import {
  ParseJobStatusSchema,
  ServerHealthSchema,
  type DocumentParseResponse,
  type ParseJobStatus,
  type ParseOptions,
  type ServerHealth,
} from './library.schema'

/**
 * Client for the OCR server (FastAPI) reached over HTTP from the webview.
 * The server allowlists this app's origins via CORS (see src/ocr_server/api.py).
 * Every response is schema-validated before use (Zod at the boundary).
 */

const env = import.meta.env as ImportMetaEnv & {
  VITE_OCR_SERVER_URL?: string
}
const rawBaseUrl = env.VITE_OCR_SERVER_URL?.trim()
const DEFAULT_BASE_URL =
  rawBaseUrl === undefined || rawBaseUrl.length === 0
    ? 'http://localhost:8300'
    : rawBaseUrl

let baseUrl = DEFAULT_BASE_URL

/** Overrides the OCR server base URL (e.g. a LAN host). */
export function setOcrBaseUrl(url: string): void {
  baseUrl = url.replace(/\/$/, '')
}

export function getOcrBaseUrl(): string {
  return baseUrl
}

async function request<T>(
  path: string,
  init: RequestInit,
  parse: (value: unknown) => T,
): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, init)
  } catch (cause) {
    throw new Error(`cannot reach OCR server at ${baseUrl} — is it running?`, {
      cause,
    })
  }
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(
      `OCR server ${String(response.status)}: ${detail.slice(0, 300)}`,
    )
  }
  return parse(await response.json())
}

/** GET /health — polled for the toolbar status dot. */
export async function getHealth(): Promise<ServerHealth> {
  return request('/health', { method: 'GET' }, (value) =>
    ServerHealthSchema.parse(value),
  )
}

/**
 * POST /parse/jobs — submits a PDF as a background job and returns the
 * initial pending status (poll with getJob).
 */
export async function submitParseJob(
  file: File,
  options: ParseOptions,
): Promise<ParseJobStatus> {
  const form = new FormData()
  form.set('file', file, file.name)
  form.set('pages', options.pages)
  form.set('dpi', String(options.dpi))
  form.set('furniture', options.furniture)
  form.set('ocr_model', options.ocrModel)
  return request('/parse/jobs', { method: 'POST', body: form }, (value) =>
    ParseJobStatusSchema.parse(value),
  )
}

/** GET /parse/jobs/{jobId} — polls job status/progress/result. */
export async function getJob(jobId: string): Promise<ParseJobStatus> {
  return request(
    `/parse/jobs/${encodeURIComponent(jobId)}`,
    { method: 'GET' },
    (value) => ParseJobStatusSchema.parse(value),
  )
}

/** Polls a job until done/error. `onProgress` fires on every poll. */
export async function pollJobUntilDone(
  jobId: string,
  onProgress: (status: ParseJobStatus) => void,
  intervalMs = 1500,
  timeoutMs = 60 * 60 * 1000,
): Promise<ParseJobStatus> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const status = await getJob(jobId)
    onProgress(status)
    if (status.status === 'done' || status.status === 'error') {
      return status
    }
    if (Date.now() > deadline) {
      throw new Error(
        `job ${jobId} timed out after ${String(timeoutMs / 1000)}s`,
      )
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

/**
 * Assembles per-page markdown into one document with invisible page
 * anchors. The markdown pane splits on these anchors for page sync.
 */
export function assembleMarkdown(
  results: DocumentParseResponse['results'],
): string {
  const chunks = results.map(
    (page) => `<!-- ocr:page:${String(page.page)} -->\n${page.markdown.trim()}`,
  )
  return `${chunks.join('\n\n')}\n`
}

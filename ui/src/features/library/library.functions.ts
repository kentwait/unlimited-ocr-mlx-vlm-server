import { convertFileSrc, invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'

import {
  TreeNodeSchema,
  SpanSchema,
  type Span,
  type TreeNode,
} from './library.schema'
import { isTauriRuntime } from './library.runtime'

/**
 * Client-safe wrappers for the app's Rust commands (src-tauri/src/lib.rs).
 * In this Tauri adaptation the Rust command layer plays the role the skill's
 * `*.server.ts` files play in a hosted TanStack Start app: the only process
 * boundary with filesystem access. These wrappers are importable from UI
 * code; the boundary validation lives in the Rust commands plus the schema
 * types used by callers. Browser (non-Tauri) mode degrades: commands make
 * no invoke calls and resolve to null — the UI shows its empty states.
 */

/** Opens the OS folder picker and returns the chosen directory, if any. */
export async function pickRootFolder(): Promise<string | null> {
  if (!isTauriRuntime()) return null
  const selection = await open({ directory: true, multiple: false })
  return typeof selection === 'string' ? selection : null
}

/** Registers the library root with the Rust layer (enables fs scoping). */
export async function setRoot(path: string): Promise<void> {
  if (!isTauriRuntime()) return
  await invoke('set_root', { path })
}

/** Returns the previously set library root, if the app has one. */
export async function getRoot(): Promise<string | null> {
  if (!isTauriRuntime()) return null
  const root = await invoke<string | null>('get_root')
  return root ?? null
}

/** Loads the file tree rooted at the library root (null when unset). */
export async function listTree(): Promise<TreeNode | null> {
  if (!isTauriRuntime()) return null
  const raw = await invoke<TreeNode | null>('list_tree')
  if (raw === null) {
    return null
  }
  return TreeNodeSchema.parse(raw)
}

/** Reads a UTF-8 text file inside the library root. */
export async function readTextFile(_path: string): Promise<string> {
  if (!isTauriRuntime()) {
    throw new Error('library requires the desktop app (Tauri runtime)')
  }
  return invoke<string>('read_text_file', { path: _path })
}

/** Writes a UTF-8 text file inside the library root (parent must exist). */
export async function writeTextFile(
  _path: string,
  contents: string,
): Promise<void> {
  if (!isTauriRuntime()) {
    throw new Error('library requires the desktop app (Tauri runtime)')
  }
  await invoke('write_text_file', { path: _path, contents })
}

/** Sibling artifact paths for a PDF: <stem>.md and <stem>.spans.jsonl. */
export function markdownPathFor(pdfPath: string): string {
  return pdfPath.replace(/\.pdf$/i, '.md')
}

export function spansPathFor(pdfPath: string): string {
  return `${pdfPath.replace(/\.pdf$/i, '')}.spans.jsonl`
}

/**
 * Picks the reading position from page/chunk tops relative to the scroll
 * container: the last entry whose top sits above the anchor line (25% down
 * the viewport). Entries must arrive in page-ascending order. Anchors sync
 * to a discrete page instead of chasing smooth-scroll positions.
 */
export function pickReadingPage(
  entries: { page: number; top: number }[],
  line: number,
): number | null {
  let best: number | null = null
  for (const entry of entries) {
    if (entry.top <= line) best = entry.page
  }
  return best
}

/**
 * Reads a PDF's bytes for preview/upload. Inside Tauri this goes through the
 * fs plugin (same root scope as the asset protocol, but a transport that
 * actually delivers bytes to fetch-hostile WebKit paths); outside Tauri it
 * falls back to fetch, which degrades to the usual load error.
 */
export async function readPdfBytes(path: string): Promise<Uint8Array> {
  if (isTauriRuntime()) {
    const { readFile } = await import('@tauri-apps/plugin-fs')
    return readFile(path)
  }
  const response = await fetch(convertFileSrc(path))
  if (!response.ok) {
    throw new Error(`fetch failed (${String(response.status)})`)
  }
  return new Uint8Array(await response.arrayBuffer())
}

export type FsDebug = {
  path: string
  canonicalPath: string | null
  root: string | null
  allowed: boolean
  allowedCanonical: boolean
}

/**
 * Asks the Rust layer whether the fs scope covers a path (literal and
 * canonical spellings). Null outside the Tauri runtime. Used to annotate
 * preview load failures with a definitive scope verdict.
 */
export async function debugFs(path: string): Promise<FsDebug | null> {
  if (!isTauriRuntime()) return null
  return invoke<FsDebug>('debug_fs', { path })
}

/**
 * Parses a spans JSONL sidecar into a per-page map. Throws on malformed
 * lines — callers decide whether that is fatal (fresh load) or a warning
 * (post-OCR save keeps its markdown, overlay goes off).
 */
export function parseSpansJsonl(jsonl: string): Map<number, Span[]> {
  const byPage = new Map<number, Span[]>()
  for (const line of jsonl.split('\n')) {
    const trimmed = line.trim()
    if (trimmed.length === 0) continue
    const span = SpanSchema.parse(JSON.parse(trimmed) as unknown)
    const list = byPage.get(span.page) ?? []
    list.push(span)
    byPage.set(span.page, list)
  }
  return byPage
}

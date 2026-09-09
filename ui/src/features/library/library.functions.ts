import { invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'

import { TreeNodeSchema, type TreeNode } from './library.schema'
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

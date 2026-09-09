// Detects whether the app is running inside a Tauri webview (with the Rust
// command layer) or as a plain browser page (dev preview / degraded mode).
// In browser mode, Tauri invoke() is unavailable and the Rust commands that
// back the library feature cannot run; callers degrade to empty states.
export function isTauriRuntime(): boolean {
  return (
    typeof window !== 'undefined' &&
    ('__TAURI_INTERNALS__' in window || '__TAURI__' in window)
  )
}

/** Reason the library feature is unavailable in this runtime, if it is. */
export function runtimeNotice(): string | null {
  return isTauriRuntime()
    ? null
    : 'desktop shell required — open the app (or `bun tauri dev`) for library access'
}

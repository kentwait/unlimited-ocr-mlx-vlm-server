// Container-local scroll jumps for the synced panes. Never use
// Element.scrollIntoView() here: it aligns the target against EVERY
// scrollable ancestor, including the document itself, so a chunk-follow
// issued while the sidecar loads can yank the whole webview and clip the
// top chrome. This helper moves only the given pane container.
export function scrollChildIntoView(
  container: HTMLElement,
  el: HTMLElement,
  block: 'start' | 'center' = 'start',
): void {
  const box = container.getBoundingClientRect()
  const rect = el.getBoundingClientRect()
  const delta =
    block === 'center'
      ? rect.top - box.top - (box.height - rect.height) / 2
      : rect.top - box.top
  container.scrollTo({ top: container.scrollTop + delta, behavior: 'auto' })
}

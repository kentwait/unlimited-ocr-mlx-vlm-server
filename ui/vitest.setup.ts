import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})

// jsdom has no layout engine: stub scrollTo (used by the panes' page sync)
// and pointer capture (used by the pane divider) so component tests exercise
// those paths. This setup file only runs under vitest, so unconditional
// assignment is safe. Guarded: pure-logic tests run in the node environment.
if (typeof Element !== 'undefined') {
  Element.prototype.scrollTo = function hush(): void {
    // no-op in tests
  }
  if (!('setPointerCapture' in Element.prototype)) {
    Object.assign(Element.prototype, {
      setPointerCapture() {
        // no-op in tests
      },
      releasePointerCapture() {
        // no-op in tests
      },
    })
  }
}

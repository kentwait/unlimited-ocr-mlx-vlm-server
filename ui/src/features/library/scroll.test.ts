// @vitest-environment jsdom
import { describe, expect, it, vi } from 'vitest'

import { scrollChildIntoView } from './scroll'

function box(top: number, height: number): DOMRect {
  return {
    top,
    height,
    bottom: top + height,
    left: 0,
    right: 0,
    width: 0,
    x: 0,
    y: top,
    toJSON: () => ({}),
  }
}

describe('scrollChildIntoView', () => {
  it('scrolls only the container, never the document', () => {
    const container = document.createElement('div')
    const el = document.createElement('div')
    container.appendChild(el)
    container.getBoundingClientRect = () => box(100, 500)
    el.getBoundingClientRect = () => box(400, 50)
    const scrollTo = vi.fn()
    container.scrollTo = scrollTo
    const scrollIntoView = vi.fn()
    el.scrollIntoView = scrollIntoView

    scrollChildIntoView(container, el, 'start')

    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith({
      top: container.scrollTop + 300,
      behavior: 'auto',
    })
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('centers the target for block=center', () => {
    const container = document.createElement('div')
    const el = document.createElement('div')
    container.getBoundingClientRect = () => box(100, 500)
    el.getBoundingClientRect = () => box(400, 50)
    const scrollTo = vi.fn()
    container.scrollTo = scrollTo

    scrollChildIntoView(container, el, 'center')

    // (400 - 100) - (500 - 50) / 2 = 75
    expect(scrollTo).toHaveBeenCalledWith({
      top: container.scrollTop + 75,
      behavior: 'auto',
    })
  })
})

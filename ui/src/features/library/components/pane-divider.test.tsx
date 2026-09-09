// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PaneDivider } from './pane-divider'

describe('PaneDivider', () => {
  it('reports drag distance on pointer movement', () => {
    const onDrag = vi.fn()
    render(<PaneDivider label="resize" onDrag={onDrag} />)
    const handle = screen.getByRole('separator', { name: 'resize' })
    fireEvent.pointerDown(handle, { clientX: 100, pointerId: 1 })
    fireEvent.pointerMove(handle, { clientX: 130 })
    fireEvent.pointerUp(handle)
    expect(onDrag).toHaveBeenCalledWith(30)
  })

  it('ignores movement without a preceding pointer down', () => {
    const onDrag = vi.fn()
    render(<PaneDivider label="resize" onDrag={onDrag} />)
    fireEvent.pointerMove(screen.getByRole('separator'))
    expect(onDrag).not.toHaveBeenCalled()
  })

  it('nudges with arrow keys', () => {
    const onDrag = vi.fn()
    render(<PaneDivider label="resize" onDrag={onDrag} step={10} />)
    const handle = screen.getByRole('separator')
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    expect(onDrag).toHaveBeenNthCalledWith(1, 10)
    expect(onDrag).toHaveBeenNthCalledWith(2, -10)
  })
})

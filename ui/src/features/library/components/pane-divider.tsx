import { useRef } from 'react'

type PaneDividerProps = {
  label: string
  /** Called with the horizontal drag distance in pixels (+ widens left). */
  onDrag: (dx: number) => void
  /** Keyboard step in pixels. */
  step?: number
}

/**
 * Draggable (and keyboard-adjustable) vertical divider between panes.
 * Pointer capture keeps the drag alive outside the handle.
 */
export function PaneDivider({
  label,
  onDrag,
  step = 10,
}: PaneDividerProps): React.JSX.Element {
  const lastX = useRef<number | null>(null)

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      tabIndex={0}
      className="w-1.5 shrink-0 cursor-col-resize touch-none bg-transparent transition-colors hover:bg-primary/30 focus-visible:bg-primary/40 focus-visible:outline-none"
      onPointerDown={(event) => {
        lastX.current = event.clientX
        event.currentTarget.setPointerCapture(event.pointerId)
      }}
      onPointerMove={(event) => {
        if (lastX.current === null) return
        onDrag(event.clientX - lastX.current)
        lastX.current = event.clientX
      }}
      onPointerUp={() => {
        lastX.current = null
      }}
      onPointerCancel={() => {
        lastX.current = null
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') {
          event.preventDefault()
          onDrag(-step)
        } else if (event.key === 'ArrowRight') {
          event.preventDefault()
          onDrag(step)
        }
      }}
    />
  )
}

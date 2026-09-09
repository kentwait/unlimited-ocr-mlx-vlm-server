import type { HTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

/** Renders an inline status or error message. */
export function Alert({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn(
        'rounded-2xl border border-destructive/30 bg-destructive/8 px-4 py-3 text-sm text-destructive',
        className,
      )}
      data-slot="alert"
      role="alert"
      {...props}
    />
  )
}

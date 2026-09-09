import type { HTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

/** Renders compact supporting metadata. */
export function Badge({
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement>): React.JSX.Element {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-semibold tracking-wide text-muted-foreground',
        className,
      )}
      data-slot="badge"
      {...props}
    />
  )
}

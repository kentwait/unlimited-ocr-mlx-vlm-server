import type { HTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

/** Renders a shared raised content surface. */
export function Card({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn(
        'rounded-3xl border border-border/80 bg-card text-card-foreground shadow-sm',
        className,
      )}
      data-slot="card"
      {...props}
    />
  )
}

/** Renders the heading region of a card. */
export function CardHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn('flex flex-col gap-2 p-6', className)}
      data-slot="card-header"
      {...props}
    />
  )
}

/** Renders the primary content region of a card. */
export function CardContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      className={cn('p-6 pt-0', className)}
      data-slot="card-content"
      {...props}
    />
  )
}

import type { InputHTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

/** Renders the shared single-line text input. */
export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>): React.JSX.Element {
  return (
    <input
      className={cn(
        'h-11 w-full rounded-xl border border-input bg-background px-3 text-sm text-foreground shadow-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      data-slot="input"
      {...props}
    />
  )
}

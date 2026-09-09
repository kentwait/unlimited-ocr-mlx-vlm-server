import type { TextareaHTMLAttributes } from 'react'

import { cn } from '#/lib/cn'

/** Renders the shared multiline text input. */
export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>): React.JSX.Element {
  return (
    <textarea
      className={cn(
        'min-h-32 w-full resize-y rounded-xl border border-input bg-background px-3 py-3 text-sm text-foreground shadow-xs outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      data-slot="textarea"
      {...props}
    />
  )
}

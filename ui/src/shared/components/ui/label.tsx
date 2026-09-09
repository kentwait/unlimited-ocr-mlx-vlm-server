import * as LabelPrimitive from '@radix-ui/react-label'
import type { ComponentProps } from 'react'

import { cn } from '#/lib/cn'

/** Renders an accessible label for a form control. */
export function Label({
  className,
  ...props
}: ComponentProps<typeof LabelPrimitive.Root>): React.JSX.Element {
  return (
    <LabelPrimitive.Root
      className={cn('text-sm font-semibold text-foreground', className)}
      data-slot="label"
      {...props}
    />
  )
}

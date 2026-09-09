import * as DialogPrimitive from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'

/** Props for the shared modal dialog composition. */
export type DialogProps = {
  children: ReactNode
  description: string
  onOpenChange?: (open: boolean) => void
  open?: boolean
  title: string
  trigger?: ReactNode
}

/** Renders an accessible modal dialog with a standard heading and close action. */
export function Dialog({
  children,
  description,
  onOpenChange,
  open,
  title,
  trigger,
}: DialogProps): React.JSX.Element {
  const rootProps = {
    onOpenChange,
    open,
  }
  return (
    <DialogPrimitive.Root
      {...(rootProps.onOpenChange
        ? { onOpenChange: rootProps.onOpenChange }
        : {})}
      {...(rootProps.open === undefined ? {} : { open: rootProps.open })}
    >
      {trigger ? (
        <DialogPrimitive.Trigger asChild>{trigger}</DialogPrimitive.Trigger>
      ) : null}
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-foreground/35 backdrop-blur-sm data-[state=closed]:animate-out data-[state=open]:animate-in motion-reduce:animate-none" />
        <DialogPrimitive.Content
          className="fixed left-1/2 top-1/2 z-50 grid max-h-[90vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-5 overflow-y-auto rounded-3xl border border-border bg-card p-6 text-card-foreground shadow-xl outline-none data-[state=closed]:animate-out data-[state=open]:animate-in motion-reduce:animate-none"
          data-slot="dialog-content"
        >
          <div className="pr-10">
            <DialogPrimitive.Title className="font-display text-2xl font-semibold">
              {title}
            </DialogPrimitive.Title>
            <DialogPrimitive.Description className="mt-2 text-sm leading-relaxed text-muted-foreground">
              {description}
            </DialogPrimitive.Description>
          </div>
          {children}
          <DialogPrimitive.Close
            aria-label="Close dialog"
            className="absolute right-5 top-5 grid size-9 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
          >
            <X aria-hidden="true" className="size-4" />
          </DialogPrimitive.Close>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

import { createRouter, type ErrorComponentProps } from '@tanstack/react-router'

import { routeTree } from './routeTree.gen'

/** Creates a fresh router instance for each application request or browser runtime. */
export function getRouter(): ReturnType<typeof createRouter> {
  return createRouter({
    routeTree,
    defaultPreload: 'intent',
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
    defaultErrorComponent: DefaultErrorComponent,
    defaultNotFoundComponent: NotFoundComponent,
  })
}

function NotFoundComponent(): React.JSX.Element {
  return (
    <main className="grid min-h-screen place-items-center p-6 text-center">
      <section>
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">
          404
        </p>
        <h1 className="mt-3 font-display text-4xl font-semibold">Not found.</h1>
      </section>
    </main>
  )
}

function DefaultErrorComponent({
  reset,
}: ErrorComponentProps): React.JSX.Element {
  return (
    <main className="grid min-h-screen place-items-center p-6 text-center">
      <section className="max-w-lg">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-destructive">
          Something went wrong
        </p>
        <h1 className="mt-3 font-display text-4xl font-semibold">
          The library could not be opened.
        </h1>
        <p className="mt-4 leading-relaxed text-muted-foreground">
          Try the request again. Internal error details are not displayed here.
        </p>
        <div className="mt-7">
          <button
            className="inline-flex rounded-full border border-border bg-background px-5 py-3 text-sm font-semibold text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={reset}
            type="button"
          >
            Try again
          </button>
        </div>
      </section>
    </main>
  )
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof getRouter>
  }
}

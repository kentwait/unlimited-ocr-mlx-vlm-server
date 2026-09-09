# Server Functions and Environment Boundaries

Use this reference before adding server-only logic, database access, private environment access, filesystem work, or client/server-safe feature and app utilities.

Source basis: TanStack Start server function documentation, code execution and import-protection guidance, and source-backed server function transport behavior.

## Contents

- [Mental Model](#mental-model)
- [Public API Surface](#public-api-surface)
- [Basic Builder Shape](#basic-builder-shape)
- [Transport Semantics](#transport-semantics)
- [Inputs and Validation](#inputs-and-validation)
- [File Organization](#file-organization)
- [Where to Call Server Functions](#where-to-call-server-functions)
- [Serialization and Responses](#serialization-and-responses)
- [Streaming Results](#streaming-results)
- [Same-Origin and CSRF](#same-origin-and-csrf)
- [Execution Boundary Helpers](#execution-boundary-helpers)
- [Import Protection](#import-protection)
- [Boundary Checklist](#boundary-checklist)

## Mental Model

`createServerFn` defines server-only logic that can be imported and called from Start app code. In client bundles, the implementation is replaced with an RPC stub. On the server, Start can call the actual implementation directly.

Use server functions for app-internal fullstack work:

- DB queries and mutations.
- Private environment variables.
- Filesystem or server SDK access.
- Auth/session-backed logic called by loaders or components.

Use server routes, not server functions, for public APIs, raw endpoints, and webhooks.

## Public API Surface

For Start app code, import server-function and execution-boundary helpers from `@tanstack/react-start`:

```tsx
import {
  createClientOnlyFn,
  createCsrfMiddleware,
  createIsomorphicFn,
  createMiddleware,
  createServerFn,
  createServerOnlyFn,
  createStart,
  Hydrate,
  useServerFn,
} from '@tanstack/react-start'
```

Import request, response, cookie, and session helpers from `@tanstack/react-start/server` only in server-only code.

## Basic Builder Shape

```tsx
import { createServerFn } from '@tanstack/react-start'

export const getData = createServerFn().handler(() => {
  return { message: 'Hello from server!' }
})

export const saveData = createServerFn({ method: 'POST' }).handler(() => {
  return { success: true }
})
```

`GET` is the default method. Prefer `GET` for idempotent reads and `POST` for mutations and forms.

## Transport Semantics

Source-level behavior to account for:

- GET payloads are encoded into a `payload` query parameter and rejected above 1 MB.
- GET server functions do not support `FormData`; use POST for forms and uploads.
- Non-GET server functions support JSON and form content types, including multipart `FormData`.
- Calling a server function with the wrong HTTP method returns `405` with an `Allow` header.
- Raw `Response` returns are supported; use them only when status, headers, redirects, or body type are part of the contract.
- Redirects, not-found outcomes, and thrown errors should propagate through Start/TanStack Router handling instead of being wrapped as successful payloads.
- Static imports of server functions are transformed into client RPC stubs; dynamic imports of server functions are not the normal supported pattern.

## Inputs and Validation

Server functions accept one logical input under `data` at the call site. Add `.validator(...)` for runtime validation and type inference.

```tsx
import { z } from 'zod'

const GreetUserInput = z.object({ name: z.string().min(1) })

export const greetUser = createServerFn({ method: 'GET' })
  .validator(GreetUserInput)
  .handler(({ data }) => {
    return `Hello, ${data.name}!`
  })

await greetUser({ data: { name: 'Ada' } })
```

Use the project's established runtime schema library, or default to Zod in a
greenfield app as directed by **ts-coder**. Pass the schema to `.validator(...)`;
do not use a type-only identity callback for untrusted data. Older
`inputValidator` APIs are deprecated in source comments.

## File Organization

Organize server behavior with its owning feature. See
[feature-architecture.md](feature-architecture.md) for the full ownership and
dependency model.

```text
src/features/tasks/
  pages/
    tasks-page.tsx       # feature page, can import *.functions.ts
  components/
    task-list.tsx        # feature UI, never imports *.server.ts
  hooks/
    use-task-filter.ts   # feature React behavior
  tasks.schema.ts     # client-safe schemas/types/constants
  tasks.server.ts     # DB queries/mutations, imports private helpers
  tasks.functions.ts  # createServerFn wrappers, safe to import from routes/components
```

Rules:

- Keep feature business UI, hooks, schemas, server functions, and server-only
  operations in the same feature slice. Route modules import client-safe
  feature exports and retain route configuration.
- `*.functions.ts` exports server functions and can be imported by routes, loaders, components, and hooks.
- `*.server.ts` contains code that must never enter the client bundle.
- Unsuffixed feature, shared, and app-utility files must stay client-safe.
- Import `*.server.ts` only inside server function handlers, server route handlers, or other server-only modules.
- Put cross-cutting helpers usable from features, routes, `src/router.tsx`,
  `src/start.ts`, or custom entries in `src/lib`. Use `*.server.ts` or
  `*.client.ts` suffixes there when the utility has an environment boundary.
- A feature public API or barrel imported by client code must never re-export
  `*.server.ts` values.

## Where to Call Server Functions

Server functions may be called from route loaders, components/hooks, event handlers, and other server functions.

Loader example:

```tsx
export const Route = createFileRoute('/posts')({
  loader: () => getServerPosts(),
})
```

Component/query integration example:

```tsx
function PostList() {
  const getPosts = useServerFn(getServerPosts)
  const { data } = useQuery({ queryKey: ['posts'], queryFn: () => getPosts() })
  return <Posts data={data} />
}
```

Static imports of server functions into client components are safe because the build replaces implementations with RPC stubs. Avoid dynamic imports of server functions.

## Serialization and Responses

- Return plain serializable data for most app-internal calls.
- Return `Response` only when status, headers, redirects, or body type are part of the contract.
- Validate inputs because data crosses a network boundary.
- Avoid returning non-serializable objects unless the app configures serialization adapters through `createStart` or plugin adapters.

## Streaming Results

Server functions can return typed `ReadableStream<T>` values or async generators when the app needs incremental data. Keep the stream item type explicit and consume it deliberately on the client.

```tsx
export const streamMessages = createServerFn().handler(async function* () {
  yield { text: 'Starting' }
  yield { text: 'Done' }
})
```

Use streaming for progressive output, not ordinary CRUD responses. For normal data loading, return plain serializable data so cache invalidation, errors, and UI state stay simple.

Consume `ReadableStream` results with `getReader()` and async generator results with `for await`. Keep stream chunks small, typed, and documented at the call site.

## Same-Origin and CSRF

Server functions are same-origin RPC endpoints for the Start app. If the app does not define `src/start.ts`, Start installs CSRF middleware automatically for server functions. If the app defines `src/start.ts`, add CSRF middleware explicitly or Start warns.

```tsx
import { createCsrfMiddleware, createStart } from '@tanstack/react-start'

const csrfMiddleware = createCsrfMiddleware({
  filter: (ctx) => ctx.handlerType === 'serverFn',
})

export const startInstance = createStart(() => ({
  requestMiddleware: [csrfMiddleware],
}))
```

Only disable or bypass CSRF checks when another layer deliberately enforces equivalent same-origin protections.

## Execution Boundary Helpers

`@tanstack/react-start` also provides `createServerOnlyFn`, `createClientOnlyFn`, and `createIsomorphicFn`.

Use `createServerOnlyFn` for server-only execution helpers, not as network RPC. Use `createServerFn` when client or isomorphic code needs to call server work through Start transport.

## Import Protection

Start import protection is enabled by default and protects environment-specific imports:

- Denies `*.server.*` files in client bundles.
- Denies `*.client.*` files in server bundles.
- Denies `@tanstack/react-start/server` in client environment.
- Dev usually mocks/warns; production build errors.

Do not disable import protection to work around a boundary violation until the import graph is understood and corrected.

Custom import protection can adjust patterns and switch behavior between mock-style development handling and production errors. Treat `behavior: 'mock' | 'error'` as a final config choice after the import graph is understood.

When import protection fails, inspect the graph for these common causes:

- a route component imports a `*.server.ts` helper directly
- a client-safe feature schema/type module or app utility imports a server-only helper as a side effect
- `@tanstack/react-start/server` leaks through a barrel export
- a dynamic import obscures a server function or server-only module boundary

## Boundary Checklist

- Decide if the caller is app-internal (`createServerFn`) or external/raw endpoint (`server.handlers`).
- Put DB/secrets/filesystem/private SDK calls in a server function handler or `*.server.ts` helper imported by that handler.
- Add `.validator(...)` for untrusted input.
- Pick `GET` for reads and `POST` for mutations/forms.
- If adding `src/start.ts`, include CSRF middleware for server functions unless deliberately handled elsewhere.
- Avoid dynamic imports of server functions.
- Do not read env secrets in client-safe feature/shared modules, app utilities,
  route components, or loaders.
- Keep server functions and server-only operations with their owning feature
  unless they are cross-cutting infrastructure that belongs in `src/lib`.

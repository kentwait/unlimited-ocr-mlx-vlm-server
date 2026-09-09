# Forms, Auth, Sessions, and Middleware

Use this reference when adding write flows, form state, route data revalidation, sessions, authenticated data, request context, logging, observability, or global Start behavior.

Source basis: TanStack Start documentation, authentication/session guidance, database guidance, middleware guidance, and source-backed behavior for request/function middleware and server runtime helpers.

## Contents

- [Default Write Flow](#default-write-flow)
- [Form UI Checklist](#form-ui-checklist)
- [Native Forms and FormData](#native-forms-and-formdata)
- [Mutation Patterns](#mutation-patterns)
- [`router.invalidate()`](#routerinvalidate)
- [Data Access Boundary](#data-access-boundary)
- [Sessions](#sessions)
- [Protect Data First](#protect-data-first)
- [Current User at the Root](#current-user-at-the-root)
- [Middleware Types](#middleware-types)
- [Passing Context](#passing-context)
- [Request, Response, Cookie, and Session Helpers](#request-response-cookie-and-session-helpers)
- [Global Start Instance](#global-start-instance)

## Default Write Flow

For app-internal mutations, use a POST server function, call it from UI, then invalidate route data if the current page shows affected data.

```tsx
// src/features/items/items.functions.ts
import { createServerFn } from '@tanstack/react-start'
import { z } from 'zod'

const CreateItemInput = z.object({ title: z.string().min(1) })

export const getItems = createServerFn({ method: 'GET' }).handler(() => {
  return listItemsFromStore()
})

export const createItem = createServerFn({ method: 'POST' })
  .validator(CreateItemInput)
  .handler(({ data }) => insertItem(data))
```

```tsx
// src/routes/items.tsx
import { createFileRoute } from '@tanstack/react-router'
import { getItems } from '../features/items/items.functions'
import { ItemsPage } from '../features/items/pages/items-page'

export const Route = createFileRoute('/items')({
  loader: () => getItems(),
  component: ItemsPage,
})
```

```tsx
// src/features/items/pages/items-page.tsx
import { getRouteApi, useRouter } from '@tanstack/react-router'
import { createItem } from '../items.functions'
import { ItemsView } from '../components/items-view'

const itemsRoute = getRouteApi('/items')

export function ItemsPage() {
  const router = useRouter()
  const items = itemsRoute.useLoaderData()

  async function onCreate(title: string) {
    await createItem({ data: { title } })
    await router.invalidate()
  }

  return <ItemsView items={items} onCreate={onCreate} />
}
```

## Form UI Checklist

- Call `event.preventDefault()` for client-handled forms.
- Disable submit controls while a mutation is in flight.
- Clear stale errors before retrying.
- Validate on the server with `.validator(...)`, even if the form also validates on the client.
- Return structured validation results for expected field errors.
- Refresh affected route data with `router.invalidate()` after successful writes.

Keep the route path and loader in `src/routes`. Keep feature-specific forms,
mutation UI, and server-function wrappers in the feature slice. Use
`getRouteApi()` in an extracted page instead of importing its route module's
`Route` object.

Use server routes instead of server functions when the form endpoint needs exact `Request`/`Response` behavior, public access, redirects, uploads, callbacks, or webhook semantics.

## Native Forms and `FormData`

Server functions expose `.url` for native form actions. Use it when progressive enhancement, non-JS submission, or browser-native file upload behavior matters.

```tsx
import { z } from 'zod'

const uploadAvatar = createServerFn({ method: 'POST' })
  .validator((formData: FormData) => ({
    file: z.instanceof(File).parse(formData.get('avatar')),
  }))
  .handler(({ data }) => {
    return Response.json({ uploaded: data.file.name })
  })

function AvatarForm() {
  return (
    <form action={uploadAvatar.url} method="POST" encType="multipart/form-data">
      <input name="avatar" type="file" />
      <button type="submit">Upload</button>
    </form>
  )
}
```

For client-handled submission, collect a `FormData` instance and call `uploadAvatar({ data: formData })`. Use POST; GET server functions do not support `FormData`.

Native form actions trade client-side control for progressive enhancement. If the UI needs optimistic updates, local pending state, or query library mutation callbacks, handle submit in React and call the server function directly.

## Mutation Patterns

- Direct calls: call `serverFn({ data })` from event handlers and then `router.invalidate()` when active loader data changed.
- React-aware calls: wrap with `useServerFn(serverFn)` when a component or hook integration wants a local callable.
- Query-library integration: use the wrapped server function in mutation/query callbacks, then invalidate the router and any query cache that duplicates the same data.

## `router.invalidate()`

Use `router.invalidate()` after mutations that affect active loader-backed UI, such as create/update/delete actions, login/logout, or mutations that change parent/sibling route data.

Avoid unnecessary invalidation when the mutation returns all data needed for local state and no route loader depends on it, or when the app navigates immediately to a destination that fetches fresh data.

## Data Access Boundary

Use this provider-neutral boundary:

```text
client/browser UI
  -> route loader or event handler
    -> createServerFn wrapper or server route handler
      -> server-only DB/auth/session helper
        -> database/provider/private SDK
```

Do not import DB clients, private SDKs, or secret-reading modules directly into components or route loaders.

## Sessions

Start exposes session helpers from `@tanstack/react-start/server`, including `useSession`, `getSession`, `updateSession`, and `clearSession`.

```tsx
import { useSession } from '@tanstack/react-start/server'
import { env } from '../../lib/env.server'

type SessionData = {
  userId?: string
  email?: string
  role?: string
}

export function useAppSession() {
  return useSession<SessionData>({
    name: 'app-session',
    password: env.SESSION_SECRET,
    cookie: {
      secure: env.NODE_ENV === 'production',
      sameSite: 'lax',
      httpOnly: true,
    },
  })
}
```

Keep session helpers and the runtime-validated `env.server.ts` module
server-only. Session passwords should be at least 32 characters. Use
`httpOnly`, production `secure`, and `sameSite: 'lax'` cookies unless the app
has a more specific security design.

Place cross-cutting session setup, provider adapters, and request-wide auth
utilities in focused `src/lib/*.server.ts` modules when they are used by
multiple features or Start entries. Keep feature-specific login, profile, or
authorization behavior in its owning feature.

## Protect Data First

Route guards improve navigation UX but are not the security boundary. Every server function or server route that returns or mutates private data should authorize internally.

```tsx
export async function requireCurrentUser() {
  const session = await useAppSession()
  const userId = session.data.userId
  if (!userId) {
    throw redirect({ to: '/login' })
  }

  const user = await getUserById(userId)
  if (!user) {
    throw redirect({ to: '/login' })
  }

  return user
}
```

Then add route protection for UX:

```tsx
export const Route = createFileRoute('/_authed')({
  beforeLoad: async ({ location }) => {
    const user = await getCurrentUserFn()
    if (!user) {
      throw redirect({ to: '/login', search: { redirect: location.href } })
    }
    return { user }
  },
})
```

Server functions must still re-check authorization.

## Current User at the Root

A common auth shape is:

1. define a `fetchUser` server function that reads the session and returns the current user or `null`
2. call it from the root route `beforeLoad`
3. return `{ user }` in route context
4. use pathless protected routes for UX redirects
5. re-check auth inside private server functions and server routes

This gives the UI a typed current-user context without making route guards the only security boundary.

Provider middleware follows the same shape: install provider request middleware, such as Clerk or AuthKit middleware, in `src/start.ts` with `createStart(() => ({ requestMiddleware: [...] }))`, then authorize private server functions and server routes with provider-backed server helpers.

## Middleware Types

| Type | Scope | Methods | Use for |
| --- | --- | --- | --- |
| Request middleware | SSR, server routes, server functions | `.server()` | Auth/session context, logging, headers, request-wide policies. |
| Function middleware | Server functions specifically | `.client()`, `.server()`, `.validator()` | Server function input/context handling and client RPC behavior. |

Request middleware cannot depend on function middleware. Function middleware can depend on request middleware.

Basic request middleware:

```tsx
import { createMiddleware } from '@tanstack/react-start'

const loggingMiddleware = createMiddleware().server(async ({ next, request }) => {
  console.info('request', request.url)
  return next()
})
```

Call `next()` unless intentionally short-circuiting the request.

## Passing Context

Middleware can pass context downstream:

```tsx
const userMiddleware = createMiddleware().server(async ({ next, request }) => {
  const user = await readUserFromRequest(request)
  return next({ context: { user } })
})
```

Server routes can read `context` in handlers. Server functions can apply middleware with `.middleware([...])` and read `context` in handlers.

Middleware may mutate response headers after `await next()` returns when it needs to add tracing, cache, or diagnostic headers. Do not trust client-sent context; derive authorization, tenant, and role context from server-side request/session/provider data.

## Request, Response, Cookie, and Session Helpers

Server-only modules can use helpers from `@tanstack/react-start/server` inside Start's server runtime context:

- request: `getRequest`, `getRequestHeaders`, `getRequestHeader`, `getRequestIP`, `getRequestHost`, `getRequestUrl`, `getRequestProtocol`
- response: `setResponseHeaders`, `getResponseHeaders`, `setResponseHeader`, `removeResponseHeader`, `setResponseStatus`
- cookies: `getCookies`, `getCookie`, `setCookie`, `deleteCookie`
- sessions: `useSession`, `getSession`, `updateSession`, `sealSession`, `unsealSession`, `clearSession`

Do not call these helpers from client code or outside Start server request handling.

## Global Start Instance

Create `src/start.ts` only when global Start configuration is needed.

```tsx
import { createCsrfMiddleware, createStart } from '@tanstack/react-start'

const csrfMiddleware = createCsrfMiddleware({
  filter: (ctx) => ctx.handlerType === 'serverFn',
})

export const startInstance = createStart(() => ({
  requestMiddleware: [csrfMiddleware, requestLogger],
  functionMiddleware: [functionLogger],
}))
```

Creating `src/start.ts` changes CSRF behavior. Add CSRF middleware for server functions unless a deliberate alternative exists.

`createStart` can also configure `serializationAdapters`, `defaultSsr`, and `serverFns.fetch`. Client-side server function fetch resolution is call-site fetch first, then later middleware, earlier middleware, `createStart` `serverFns.fetch`, and finally global `fetch`. During SSR, server functions call the server implementation directly.

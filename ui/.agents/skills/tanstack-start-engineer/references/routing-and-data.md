# Routing and Data

Use this reference when adding routes, route-owned layouts, route data, deferred data, raw endpoints, or feature pages wired into file routes.

Source basis: TanStack Start routing and server route documentation, maintained route examples, and source-backed server route behavior.

## Contents

- [One Routing System](#one-routing-system)
- [Route Module Ownership](#route-module-ownership)
- [File Route Conventions](#file-route-conventions)
- [Loaders](#loaders)
- [Params and Generated Types](#params-and-generated-types)
- [Deferred Data](#deferred-data)
- [Server Functions vs Server Routes](#server-functions-vs-server-routes)
- [Server Routes](#server-routes)
- [Router Context and TanStack Query SSR](#router-context-and-tanstack-query-ssr)
- [`serverContext`](#servercontext)
- [Route Change Checklist](#route-change-checklist)

## One Routing System

Start uses TanStack Router file-based routes under `src/routes`. A route file can define UI behavior, server route behavior, or both.

Every file route exports a `Route` constant:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { getPost } from '../features/posts/posts.functions'
import { PostPage } from '../features/posts/pages/post-page'

export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params }) => getPost({ data: params.postId }),
  component: PostPage,
})
```

The root route uses `createRootRoute` in `src/routes/__root.tsx`.

## Route Module Ownership

Keep routing-specific behavior in the route file: `createFileRoute`, the route
path, loader, `beforeLoad`, search validation, route context, head metadata,
SSR, pending/error/not-found route options, `server.handlers`, and
`Outlet`-bearing routing layouts.

Put feature pages, feature components, feature hooks, and feature business
logic under `src/features/<feature>`. Import feature pages and client-safe
feature functions into the route module instead of accumulating business UI in
`src/routes`.

An extracted page must not import the route module's `Route` object just to
call route hooks; that creates a circular dependency. Use `getRouteApi()` with
the route ID instead:

```tsx
import { getRouteApi } from '@tanstack/react-router'
import { PostList } from '../components/post-list'

const postsRoute = getRouteApi('/posts')

export function PostsPage() {
  const posts = postsRoute.useLoaderData()
  return <PostList posts={posts} />
}
```

Keep a routing-only layout in the route file. A feature shell that composes
feature UI belongs in its feature slice. The route file declares fallback
options; the fallback component may be feature-owned when it renders
feature-specific UI.

## File Route Conventions

| File | Route path |
| --- | --- |
| `src/routes/index.tsx` | `/` |
| `src/routes/about.tsx` | `/about` |
| `src/routes/posts.tsx` | `/posts` layout or page |
| `src/routes/posts.index.tsx` or `src/routes/posts/index.tsx` | `/posts/` index |
| `src/routes/posts.$postId.tsx` or `src/routes/posts/$postId.tsx` | `/posts/$postId` |
| `src/routes/rest/$.tsx` | Wildcard under `/rest` |
| `src/routes/customScript[.]js.ts` | `/customScript.js` |

Nested routes render through `<Outlet />` in parent route components. Pathless layout routes use underscore segments.

Avoid route path collisions when mixing flat and directory route styles. If two files resolve to the same route path, rename or consolidate rather than relying on generation order.

## Loaders

Loaders fetch route data. A component in the same route module may consume it
with `Route.useLoaderData()`; an extracted feature page should use
`getRouteApi()` as shown above.

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { listPosts } from '../features/posts/posts.functions'
import { PostsPage } from '../features/posts/pages/posts-page'

export const Route = createFileRoute('/posts')({
  loader: () => listPosts(),
  component: PostsPage,
})
```

Boundary rule: loaders are isomorphic. They may run on the server during SSR and on the client during navigation. Do not access secrets, private env vars, filesystem, DB clients, or private SDKs directly in loaders. Put that work in a server function.

Preferred pattern:

```tsx
// src/features/users/users.functions.ts
import { createServerFn } from '@tanstack/react-start'
import { env } from '../../lib/env.server'

export const getUsersSecurely = createServerFn().handler(() => {
  return fetch(`${env.USERS_API_URL}?key=${env.USERS_API_KEY}`)
})

// src/routes/users.tsx
import { createFileRoute } from '@tanstack/react-router'
import { getUsersSecurely } from '../features/users/users.functions'

export const Route = createFileRoute('/users')({
  loader: () => getUsersSecurely(),
})
```

Validate `env.server.ts` with Zod or the project's established runtime schema
library. Keep the server function in the owning feature and let the route own
only loader and URL behavior.

## Params and Generated Types

Route paths such as `/posts/$postId` produce typed params:

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { getPost } from '../features/posts/posts.functions'
import { PostPage } from '../features/posts/pages/post-page'

export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params: { postId } }) => getPost({ data: postId }),
  component: PostPage,
})
```

If navigation or `Route.useParams()` types look stale, regenerate the route tree by running dev/build tooling rather than editing the generated file manually.

## Deferred Data

Use deferred data when a route can render meaningful UI before slower data resolves. Keep critical content fast, put slower panels behind suspense/deferred rendering, and keep server-only work behind server functions.

## Server Functions vs Server Routes

| Situation | Use | Reason |
| --- | --- | --- |
| Loader/component/event handler needs server-only logic | `createServerFn` in the owning feature | Type-safe same-origin RPC and serialization. |
| External client, webhook, raw caller, public API, or form endpoint | Server route | Exact `Request`/`Response`, status, headers, and content type control. |
| A route page owns a small local raw endpoint | Same route file with `server.handlers` and an imported feature page | HTTP path/method ownership stays in the route while feature UI stays in its slice. |

## Server Routes

A server route is a file route with a `server` property:

```ts
import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/api/users')({
  server: {
    handlers: {
      GET: ({ request, params, context }) => {
        return Response.json({ ok: true })
      },
    },
  },
})
```

Supported methods include `ANY`, `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`, and `HEAD`.

Handlers receive `request`, `params`, `pathname`, `context`, and `next`. They can return a `Response`, return `undefined`, or call `next({ context })` to pass additional context downstream.

When a route also has UI, `next()` can defer from server-route handling back to the app route component. A server-route-only request that produces no response is an error; return an explicit `Response` when no UI fallback should handle the request.

Route-level middleware applies to all handlers:

```ts
export const Route = createFileRoute('/api/protected')({
  server: {
    middleware: [authMiddleware],
    handlers: {
      GET: () => Response.json({ ok: true }),
    },
  },
})
```

Use `createHandlers` when a specific method needs its own middleware.

Example context composition:

```ts
const attachUser = createMiddleware().server(({ next }) => {
  return next({ context: { userId: 'user-1' } })
})

export const Route = createFileRoute('/api/me')({
  server: {
    middleware: [attachUser],
    handlers: {
      GET: ({ context }) => Response.json({ userId: context.userId }),
    },
  },
})
```

## Router Context and TanStack Query SSR

Create a fresh router per request/call and put per-router dependencies in router context. For TanStack Query SSR, create a fresh `QueryClient`, pass it through router context, and call the router/query integration helper used by the app.

Use `createRootRouteWithContext<{ queryClient: QueryClient }>()` when routes need typed access to that context. Do not share one `QueryClient` across requests.

## `serverContext`

Use server/request context for values derived from the incoming request, such as auth context, headers, tracing IDs, locale, or tenant. Route middleware context becomes available to server route handlers as server context. Keep client-safe router context separate from server-only values when the value cannot be serialized or exposed.

## Route Change Checklist

- Add or edit files under the app's configured routes directory, usually `src/routes`.
- Export `Route` from each route file.
- Keep route paths, loaders, guards, route options, and `server.handlers` in
  the route file; import feature pages and client-safe feature functions.
- Use `getRouteApi()` in extracted feature pages instead of importing the
  route `Route` object.
- Use loaders for route data and server functions for server-only loader work.
- Use server routes for raw endpoint/API behavior.
- Regenerate route tree via dev/build tooling.
- Check route path collisions when moving between flat and nested naming styles.

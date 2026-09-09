---
name: tanstack-start-engineer
description: "Engineer, scaffold, extend, and review fullstack TypeScript applications built on TanStack Start. Extends ts-coder; combines with ts-qa-engineer and the React skills while specializing their feature-based architecture for file routing, route-coupled data, imports, server boundaries, build, deployment, and framework-specific test placement. Use for feature slices, file routes, loaders, server functions/routes, forms, sessions, middleware, SSR, streaming, prerendering, SPA mode, deployment, or client/server boundary debugging."
---

# TanStack Start Engineer

This skill extends **ts-coder** for TypeScript conventions and specializes those
conventions for TanStack Start fullstack applications.

Treat code blocks as focused excerpts. In generated code, add the explicit
return types and TSDoc required by **ts-coder**. Examples may omit them only
for brevity and do not override generated-code requirements.

## Inheritance and Precedence

Apply the skills together by ownership boundary:

| Skill | Owns | TanStack Start behavior |
| --- | --- | --- |
| **ts-coder** | TypeScript strictness, Node.js and pnpm requirements, validation, docs, lint/test habits | Inherited. Require Node.js LTS and pnpm without package-manager substitution. |
| **ts-qa-engineer** | Test strategy, isolation, mocks, fixtures, coverage, and test data | Inherited except for feature and route test placement defined by this skill. |
| **tanstack-start-engineer** | Start app structure, file routes, loaders, server functions, server routes, middleware, SSR/build/deploy, compiler target, client/server boundaries | Primary skill for fullstack behavior, route/data ownership, and framework build settings. |
| **react-ts-engineer** | Feature-based React component architecture, state, hooks, reusable composition, React 19 patterns | Inherit its feature ownership and shared-UI rules; override React Router v8 route-config layouts and its alias-preferred import rule. |
| **react-ts-ui-designer** | Styling, tokens, Tailwind, CVA, accessibility, responsive layout, visual states | Apply visual patterns inside feature slices or shared UI; keep server actions/data mutations governed by Start rules. |

When guidance conflicts, prefer this skill for feature and test placement,
routing, data loading, server execution, environment boundaries, app entries,
and deployment behavior. Prefer `ts-qa-engineer` for test strategy and the React
skills for component composition, state ergonomics, styling, and a11y.

## Core Model

TanStack Start is a fullstack framework built on TanStack Router. A React Start
app combines:

```text
build plugin -> router factory -> file routes -> loaders/server functions/server routes
```

## Coverage Model

Use `SKILL.md` for workflow and decision routing. Load references for
implementation details, especially when behavior depends on transport
semantics, middleware context, SSR mode, generated/plugin behavior, or
request/response helpers.

Use this layering for app code:

| Layer | Common files | Responsibility |
| --- | --- | --- |
| Build config | `vite.config.ts`, `rsbuild.config.ts` | Configure `tanstackStart()` and bundler plugins. |
| Router entry | `src/router.tsx` | Export `getRouter()` and return a new router instance per call. |
| Root document | `src/routes/__root.tsx` | Render `<HeadContent />`, route content, and `<Scripts />`. |
| UI routes | `src/routes/**/*.tsx` | Own `createFileRoute`, paths, loaders, guards, metadata, SSR, route fallbacks, `server.handlers`, and routing layouts; import feature UI. |
| Feature slices | `src/features/<feature>/` | Own feature pages, components, hooks, schemas, server functions, server-only operations, and feature tests. |
| Shared UI | `src/shared/components/` | Own genuinely cross-feature UI with no feature knowledge. |
| App utilities | `src/lib/` | Own reusable helpers and infrastructure glue used by features, routes, and entrypoints. |
| Server functions | `*.functions.ts` | Typed app-internal RPC with `createServerFn`; keep near their owning feature. |
| Server-only helpers | `*.server.ts` | DB, sessions, filesystem, private SDKs, secret env access; keep near their feature or in `src/lib` for cross-cutting infrastructure. |
| Server routes | `src/routes/api/*` or route `server.handlers` | Raw endpoints, webhooks, public APIs, exact `Request`/`Response` control. |
| Start instance | `src/start.ts` | Global middleware, serialization adapters, SSR defaults, server function fetch config. |

## App-Building Workflow

1. Inspect the existing app or repo conventions first: Node.js and pnpm versions, bundler,
   routing directory, validation library, styling system, auth/session approach,
   and test commands. Require Node.js and pnpm as defined by ts-coder.
2. Create or verify the Start skeleton: dependencies, `tanstackStart()` plugin,
  `src/router.tsx`, `src/routes/__root.tsx`, and the first feature plus route.
3. Identify the owning business feature before adding UI, hooks, schemas, or
  server work. Create those modules under `src/features/<feature>`; keep them
  in that slice until cross-feature reuse is real.
4. Add routes with `createFileRoute`; keep paths, loaders, guards, search
  validation, metadata, SSR options, and route fallbacks in `src/routes`.
  Import feature pages and client-safe feature functions into those route
  modules. Use `getRouteApi()` from extracted feature pages instead of
  importing a route `Route` object.
5. Put reusable rendered UI in `src/shared/components` only when it has no
  feature ownership. Put reusable boilerplate and infrastructure glue used by
  features, routes, or entrypoints in `src/lib`; call it an app utility, not a
  shared component.
6. Keep server-only work behind `createServerFn`, server route handlers, or
   `*.server.ts` helpers imported only by server code.
7. For writes, use POST server functions for app-internal mutations, validate
   input, show pending/error state, and call `router.invalidate()` when loader
   data is stale.
8. Add auth/session checks at the data boundary first; route guards and
   redirects are UX, not the security boundary.
9. Add middleware or `src/start.ts` only when cross-cutting request/function
   behavior is needed. If adding `src/start.ts`, include CSRF middleware for
   server functions unless the app has an explicit alternative.
10. Validate with the app's existing pnpm scripts. In repos that use Nx, prefer
  targeted project commands over broad test runs. Use `pnpm run build`,
  `pnpm run lint`, and `pnpm test` when configured.

## Decision Points

| Need | Use | Avoid |
| --- | --- | --- |
| Page URL with UI | Route module + imported feature page | Putting feature pages and business UI in the routes directory. |
| Route-coupled data | Route `loader` calling a client-safe feature server function | DB/secrets directly in loaders. |
| Extracted feature page needs route data/params/search | `getRouteApi()` with the route ID | Importing the route `Route` object and creating a circular dependency. |
| Reusable feature-agnostic UI | `src/shared/components` | Promoting feature-specific UI before genuine cross-feature reuse. |
| Reusable boilerplate or framework glue | `src/lib` app utility | Calling utilities shared components or building a catch-all `src/services` layer. |
| Client-safe reusable API wrapper | Feature client module or client-safe shared module | Putting secret-bearing logic in `src/services` because a generic React pattern said so. |
| App-internal server work | `createServerFn` | Public API semantics or webhook handling. |
| External/raw endpoint | Route `server.handlers` returning `Response` | Forcing external callers through server functions. |
| Mutation from UI | POST `createServerFn` + validation + pending state | GET mutations or trusting client validation. |
| Refresh route data after mutation | `router.invalidate()` | Manual stale loader cache assumptions. |
| Auth/session-backed private data | Server functions/routes authorize internally | Relying only on route `beforeLoad`. |
| Cross-cutting request context | `createMiddleware` and optionally `src/start.ts` | Duplicating auth/logging in every route. |

## Start Overrides for React Skills

- Specialize the inherited feature-based architecture for Start: feature pages,
  components, hooks, schemas, server functions, and server-only operations stay
  in `src/features/<feature>`; genuinely feature-agnostic reusable UI belongs in
  `src/shared/components`.
- Reuse shared primitives and compositions inside feature UI, but do not
  organize folders by visual complexity or promote feature-aware components to
  shared code.
- Use TanStack Router file routes under `src/routes`, not the generic
  `react-ts-engineer` React Router v8 route-object layout.
- Follow the Start app's configured TypeScript/Vite aliases. Relative imports
  are allowed for generated modules, framework entrypoints, and nearby modules;
  this overrides `react-ts-engineer`'s default alias-preferred convention.
- Prefer route loaders and server functions over generic `src/services` fetch
  modules for route-coupled app data.
- Keep routing-specific declarations in route files, but import feature-owned
  pages, schemas, client-safe functions, and route fallback UI as appropriate.
- Use feature modules like `*.schema.ts`, `*.functions.ts`, and `*.server.ts`
  when separating feature schemas, server function wrappers, and server-only
  implementations.
- Put cross-cutting helpers used by routes, features, `src/router.tsx`,
  `src/start.ts`, or custom entries in `src/lib`. Use `*.server.ts` and
  `*.client.ts` suffixes when those utilities have environment boundaries.
- React Hook Form, `useActionState`, and local form state are UI choices. The
  mutation boundary still belongs in POST server functions or server routes.
- Use `react-ts-ui-designer` for loading, error, empty, disabled, focus, and
  responsive visual states; use this skill to decide whether those states come
  from route pending UI, mutation state, deferred data, redirects, or errors.
- Apply `ts-qa-engineer` for test strategy and test doubles, but co-locate
  feature unit/component tests within their feature slice. Keep route
  integration tests in the app's configured non-route test location so test
  files do not become generated routes. This placement overrides the generic
  tier-directory default.

## Boundary Rules

- Treat route loaders as isomorphic. They can run during SSR and client
  navigation, so they must not import secrets, DB clients, private SDKs, or
  filesystem logic directly.
- Put secret-bearing code in `*.server.ts` helpers and call those helpers from
  server function handlers or server route handlers.
- Use `.validator(...)` with Zod or the project's established runtime schema
  library on server functions that accept untrusted input. Do not use
  type-only identity callbacks as validation.
- Prefer `GET` server functions for idempotent reads and `POST` for mutations,
  forms, and FormData.
- Keep server function imports static; avoid dynamic imports of server
  functions.
- Return plain serializable data from server functions unless raw `Response`
  semantics are intentional.
- Do not hand-edit `src/routeTree.gen.ts` in normal app work. Regenerate it via
  dev/build tooling.

## Minimal Skeleton

Create this shape first for a React Start app:

```text
src/
  router.tsx
  routes/
    __root.tsx
    index.tsx
  features/
    home/
      pages/
        home-page.tsx
```

Create `src/shared` and `src/lib` when the first proven cross-feature UI or
app utility needs them; do not pre-create empty directories.

`getRouter()` must return a fresh router instance:

```tsx
import { createRouter } from '@tanstack/react-router'
import { routeTree } from './routeTree.gen'

export function getRouter() {
  return createRouter({
    routeTree,
    defaultPreload: 'intent',
    scrollRestoration: true,
  })
}
```

The root route must render the document shell with `<HeadContent />` and
`<Scripts />`.

## Completion Checklist

- [ ] Node.js LTS and pnpm are required and their project versions were followed.
- [ ] `tanstackStart()` is configured before React's Vite plugin in Vite apps.
- [ ] `getRouter()` returns a new router instance.
- [ ] Root document includes `<HeadContent />` and `<Scripts />`.
- [ ] Routes export a `Route` constant and avoid path collisions.
- [ ] Route files own routing-specific configuration and import feature UI
  rather than accumulating feature business components.
- [ ] Each business capability has a clear feature owner under `src/features`.
- [ ] Extracted feature pages use `getRouteApi()` rather than importing a route
  `Route` object for typed route hooks.
- [ ] Cross-feature UI is feature-agnostic in `src/shared/components`; reusable
  boilerplate and infrastructure glue lives in `src/lib` app utilities.
- [ ] Server-only imports stay out of loaders/components/shared modules.
- [ ] Server functions validate input and use intentional HTTP methods.
- [ ] Private data is authorized in server functions and server routes, not only in route guards.
- [ ] React component and UI guidance was applied without replacing Start routing,
  loader, or server boundary patterns.
- [ ] If the app defines `src/start.ts`, it includes CSRF middleware for server
  functions unless an explicit alternative protects same-origin requests.
- [ ] Build/type/lint/test commands were run or the blocker was reported.

## Coverage Checklist

Use the references to cover these common fullstack areas before leaving the skill:

- [ ] App skeleton and package/import surfaces.
- [ ] Routing, loaders, params, route context, and deferred data.
- [ ] Server functions, transport semantics, streaming, and import boundaries.
- [ ] Server routes, raw endpoint behavior, and route middleware context.
- [ ] Forms, mutations, native `FormData`, and revalidation.
- [ ] Auth, sessions, request/response helpers, cookies, and authorization.
- [ ] Middleware, `createStart`, request/function context, and fetch overrides.
- [ ] SSR, selective SSR, hydration safety, pending UI, and CSP/head/scripts.
- [ ] TanStack Query SSR or other integration patterns used by the app.
- [ ] Build/deploy config, generated files, import protection, rewrites, and validation commands.

## Reference Files

Load these as needed - do not pre-load all of them:

- **[feature-architecture.md](references/feature-architecture.md)** - Feature
  slices, route ownership, shared UI, app utilities, dependency direction,
  `getRouteApi()`, and migration rules. Load when scaffolding, organizing,
  extracting, or reviewing application code.
- **[tanstack-start-app.md](references/tanstack-start-app.md)** - App skeleton,
  package setup, plugin ordering, router/root route requirements, and optional
  entries. Load when creating or reviewing a Start app scaffold.
- **[routing-and-data.md](references/routing-and-data.md)** - File routes,
  loaders, params, deferred data, and server routes. Load when adding pages,
  layouts, loaders, or API endpoints.
- **[server-boundaries.md](references/server-boundaries.md)** - Server
  functions, `*.server.ts` organization, validation, methods, serialization,
  import protection, and CSRF caveats. Load before adding DB, filesystem,
  private SDK, or secret-backed logic.
- **[forms-auth-and-middleware.md](references/forms-auth-and-middleware.md)** -
  Mutations, form state, sessions, authorization, request/function middleware,
  and `src/start.ts`. Load for writes, auth, sessions, or cross-cutting behavior.
- **[ux-build-and-validation.md](references/ux-build-and-validation.md)** -
  Error boundaries, not-found, redirects, pending/deferred UI, hydration safety,
  generated files, prerendering, SPA mode, hosting, and validation commands.
  Load before changing UX states or deployment/build behavior.
- **[source-backed-patterns.md](references/source-backed-patterns.md)** -
  Source-sensitive transport, middleware ordering, plugin schema, and
  troubleshooting edge cases. Load only when installed behavior or public docs
  are ambiguous.

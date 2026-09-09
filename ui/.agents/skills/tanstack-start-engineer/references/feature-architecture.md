# Feature-Based Application Architecture

Use this reference when scaffolding a Start app, adding a business capability, extracting route UI, deciding whether code is reusable, or reviewing application structure.

## Contents

- [Default Structure](#default-structure)
- [Ownership Rules](#ownership-rules)
- [Route Modules Are Routing Adapters](#route-modules-are-routing-adapters)
- [Shared UI Versus App Utilities](#shared-ui-versus-app-utilities)
- [Dependency Direction](#dependency-direction)
- [Tests and Migration](#tests-and-migration)
- [Review Checklist](#review-checklist)

## Default Structure

Organize app code by business capability first. Create folders only when a feature needs them; do not add empty architecture folders preemptively.

```text
src/
  routes/                         # File-route declarations and routing-specific behavior
    __root.tsx
    projects.index.tsx
    projects.$projectId.tsx
  features/
    projects/
      pages/
        projects-page.tsx
        project-detail-page.tsx
      components/
        project-card.tsx
      hooks/
        use-project-filters.ts
      projects.schema.ts
      projects.functions.ts
      projects.server.ts
  shared/
    components/                   # Reusable UI with no feature knowledge
    hooks/                        # Reusable React hooks with no feature ownership
    types/                        # Client-safe contracts with no single feature owner
  lib/                             # App utilities usable by routes, features, and entries
    cn.ts
    logger.ts
    env.server.ts
  router.tsx
  start.ts
```

A feature contains one major business capability and its UI, hooks, client-safe schemas, server-function wrappers, server-only operations, and feature tests. Subfolders such as `pages`, `components`, and `hooks` are local organizational aids inside that slice, not global horizontal layers.

## Ownership Rules

| Location | Owns | Must not own |
| --- | --- | --- |
| `src/routes` | `createFileRoute`, route paths/IDs, loaders, `beforeLoad`, search validation, route context, head metadata, SSR, pending/error/not-found route options, `server.handlers`, and `Outlet`-bearing routing layouts | Feature business UI, feature hooks, data-access implementations, or generic utilities |
| `src/features/<feature>` | Feature pages, components, hooks, feature schemas/types, server functions, server-only domain operations, and feature tests | URL registration, generated route-tree files, or another feature's internals |
| `src/shared/components` | Proven cross-feature UI primitives and compositions with no feature knowledge | Feature-specific behavior, loaders, server-only imports, or business data access |
| `src/shared/hooks` | Generic hooks reused across features with no feature ownership | Feature business rules or route registration |
| `src/shared/types` | Client-safe contracts with no single feature owner | Types that still belong to one feature or server-only types |
| `src/lib` | Reusable app utilities and infrastructure glue used by features, routes, and entrypoints: formatting helpers, logging, environment access, serialization, constants, and framework helpers | React feature components, feature business rules, or a catch-all services layer |

Use `*.server.ts` and `*.client.ts` suffixes in any location when execution boundaries require them. Keep unsuffixed modules client-safe.

## Route Modules Are Routing Adapters

Keep routing-specific behavior in the generated route directory. A normal route imports the feature page and any client-safe feature API it needs, then declares the route contract.

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { listProjects } from '../features/projects/projects.functions'
import { ProjectsPage } from '../features/projects/pages/projects-page'

export const Route = createFileRoute('/projects')({
  loader: () => listProjects(),
  component: ProjectsPage,
})
```

The page stays in the feature slice. When it needs typed loader data, params, search, route context, or navigation, use `getRouteApi()` instead of importing the route module and creating a circular dependency.

```tsx
import { getRouteApi } from '@tanstack/react-router'
import { ProjectList } from '../components/project-list'

const projectsRoute = getRouteApi('/projects')

export function ProjectsPage() {
  const projects = projectsRoute.useLoaderData()
  return <ProjectList projects={projects} />
}
```

Keep a routing-only layout, such as one that renders `<Outlet />`, in the route file. Keep a feature shell that composes feature UI in its feature slice. Declare `pendingComponent`, `errorComponent`, and `notFoundComponent` in the route file; place a feature-specific rendered component in the feature slice and import it when that improves cohesion.

Retain `server.handlers` in the route module because HTTP method and path ownership are routing concerns. Delegate feature-specific domain work to server-only feature operations without exposing those operations through client-imported barrels.

## Shared UI Versus App Utilities

Do not label all reusable code as a “shared component.” Choose the location by its responsibility:

- Put reusable rendered UI in `src/shared/components` only after it has genuine cross-feature use and no feature-specific knowledge.
- Put reusable React behavior in `src/shared/hooks` only when it has no feature owner.
- Put reusable boilerplate and infrastructure glue in `src/lib`, even when routes, `src/router.tsx`, `src/start.ts`, or custom client/server entries use it. These are app utilities, not components.
- Keep code in its feature until cross-feature reuse is real. Do not create speculative shared abstractions.

`src/lib` is not a dumping ground. Prefer a focused module such as `logger.ts`, `cn.ts`, or `env.server.ts` over a generic `utils.ts` that collects unrelated behavior.

## Dependency Direction

Prefer this direction:

```text
routes -> features -> shared/lib
entrypoints -> routes and lib
shared/lib -> never features or routes
```

Avoid feature-to-feature imports. If a dependency is genuinely required, expose a narrow, client-safe public API from the owning feature, keep the graph acyclic, and never re-export `*.server.ts` values through a module that client code can import.

## Tests and Migration

Co-locate feature unit/component tests with the feature; this overrides the
generic `ts-qa-engineer` tier-directory default. Keep route-level integration
tests in the app's configured non-route test location so they are not processed
as generated routes. Focus them on URLs, loaders, guards, route options, and
route/server-handler integration. Keep utility tests beside the utility.

Use this organization by default for greenfield apps and new features. When modifying an existing app with a different established structure, preserve its conventions unless the user asks for an explicit migration.

## Review Checklist

- Does every business capability have a clear owning feature?
- Does each route retain its path and routing-specific configuration?
- Does each feature page avoid importing a route `Route` object and use `getRouteApi()` when needed?
- Is reusable UI in `src/shared/components` only when it is genuinely feature-agnostic?
- Are reusable cross-cutting helpers in `src/lib` and usable from features, routes, and entrypoints?
- Do `shared` and `lib` avoid imports from features and routes?
- Do server-only values remain outside client-imported barrels and shared client-safe modules?

# Dependency Rules

Production imports form a directed acyclic graph.

| Importer                                | Allowed application imports                                          |
| --------------------------------------- | -------------------------------------------------------------------- |
| `src/routes`                            | client-safe feature APIs, feature pages, shared UI, `src/lib`        |
| `src/features/<feature>/pages`          | same feature, shared UI/hooks/types, `src/lib`                       |
| `src/features/<feature>/components`     | same feature client-safe modules, shared UI/hooks/types, `src/lib`   |
| `src/features/<feature>/*.functions.ts` | same feature schemas and server-only operations                      |
| `src/features/<feature>/*.server.ts`    | same feature, server-only `src/lib`, private infrastructure packages |
| `src/shared/*`                          | other shared code and `src/lib` only                                 |
| `src/lib`                               | other focused `src/lib` modules only                                 |
| `src/router.tsx` and `src/start.ts`     | generated routes and `src/lib` framework glue                        |

## Environment Rules

- Browser-reachable code must not import `*.server.ts`, Node-only modules, private SDKs,
  secret environment access, or `@tanstack/react-start/server`.
- Server function wrappers may be imported by routes and browser UI because Start
  transforms their implementation into RPC stubs.
- Static server-function imports are required. Dynamic server-function imports obscure
  the transform boundary and are unsupported by this contract.
- A client-safe barrel must not re-export a server-only value.

## Feature Dependencies

Avoid feature-to-feature imports. When a real capability dependency exists, expose a
narrow client-safe public module from the owning feature, document the direction, and
keep the graph acyclic. Move a contract to `shared` only when it has no single feature
owner.

## Enforcement

TanStack Start import protection and production builds enforce runtime-sensitive
boundaries. TypeScript, ESLint, and source-boundary tests detect part of the wider import
graph; review enforces the remaining ownership rules. Fix the import graph rather than
weakening Start import protection.

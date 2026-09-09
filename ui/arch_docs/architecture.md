# Architecture

This template organizes a TanStack Start application by business capability while
preserving the framework's file-route and runtime boundaries.

## Product Specification Flow

```text
Master PRD (Vision)
    -> focused feature or release PRD (Normative)
    -> complete or phased technical design (Normative)
    -> implementation
    -> acceptance evidence
```

Use this full flow proportionately for significant product or architecture changes.
Routine maintenance does not require ceremonial specifications.

## Runtime Flow

```text
browser or SSR request
    -> file route loader or event handler
    -> client-safe createServerFn wrapper
    -> server-only feature operation
    -> database, provider, filesystem, or private SDK
```

Routes register URLs and lifecycle behavior. Features own business-facing UI and
behavior. Server functions are typed same-origin RPC boundaries. Server-only modules
own private infrastructure access.

Raw clients, webhooks, and public APIs use route `server.handlers` because those
interfaces need exact HTTP method, status, header, and body control.

## Tauri Adaptation (This Application)

This app runs the Start router in SPA mode inside a Tauri 2 webview, so the
runtime flow above maps onto different carriers:

```text
user action
    -> feature component or hook
    -> client-safe Tauri invoke wrapper (*.functions.ts)
    -> Rust command (src-tauri) for filesystem, or OCR server over HTTP
```

- There are no `createServerFn` wrappers and no `*.server.ts` modules: the Rust
  command layer is the privileged boundary (root-scoped filesystem), and the
  FastAPI OCR server is an external process reached through CORS-allowlisted
  fetch calls validated with Zod at the boundary.
- Routes stay single-`/` (Tauri serves static assets without SPA path
  fallback); UI state lives in search params and component state.
- `src-tauri` is outside the `routes -> features -> shared/lib` graph: Rust
  owns its side, TypeScript owns its side, and `*.functions.ts` is the seam.

## Default Source Shape

Template shape (the reusable pattern), with this app's carriers in brackets:

```text
src/
├── routes/
│   ├── __root.tsx
│   ├── notes.index.tsx              [this app: index.tsx only]
│   └── notes.$noteId.tsx
├── features/
│   └── notes/                       [this app: library/]
│       ├── pages/
│       ├── components/
│       ├── notes.schema.ts
│       ├── notes.functions.ts       [this app: + library.ocr.ts (HTTP client)]
│       └── notes.server.ts          [this app: none — Rust commands instead]
├── shared/
│   └── components/
├── lib/
├── router.tsx
└── start.ts                         [this app: none — SPA mode, no server entry]
```

A feature contains one business capability. Its optional subfolders are local
organization, not application-wide horizontal layers. Do not pre-create empty folders.

## Route Modules Are Routing Adapters

Route modules own `createFileRoute`, paths, loaders, guards, search and parameter
validation, metadata, SSR behavior, route fallbacks, and routing layouts. They import
feature pages and client-safe feature functions.

An extracted feature page uses `getRouteApi('/route/id')` for loader data, params,
search, and navigation. It must not import the route module's `Route` object because
that creates a circular dependency.

## Server And Browser Boundaries

- `*.server.ts` is server-only and protected from browser bundles by Start.
- `*.client.ts` is browser-only when a feature needs IndexedDB, DOM, or other client
  infrastructure.
- Unsuffixed modules remain safe for both runtimes.
- Route loaders may execute during SSR and browser navigation, so they never import
  server-only infrastructure directly.
- Server functions accept one logical `data` input and validate it at runtime.
- Server functions return plain serializable data unless raw response semantics are
  intentional.
- Global `src/start.ts` explicitly installs CSRF middleware for server functions.

## Shared UI And App Utilities

`src/shared/components` contains reusable rendered UI with no feature knowledge.
`src/lib` contains focused framework glue and utilities such as class-name merging,
environment parsing, logging, and serialization.

Neither location is a dumping ground. Keep feature code in its feature until actual
cross-feature reuse makes another owner clearer.

## Authentication Extension

Authentication is intentionally not implemented. When an application adds it:

1. Keep session/provider access in `src/lib/*.server.ts` or an owning auth feature.
2. Resolve a trusted principal from server request or session data.
3. Authorize every private server function and server route internally.
4. Add route guards only for redirect and navigation UX.
5. Validate trusted origins, use `httpOnly`, `sameSite`, and production `secure`
   cookies, and retain CSRF protection.
6. Record the selected identity and authorization model in an application ADR and
   technical design.

## Persistence Extension

The Notes store is process-local reference code. A real persistence adapter belongs in
the owning feature or focused server utility and remains behind server functions.
Database selection, migrations, transaction boundaries, tenancy, backup, restoration,
and deployment sequencing require an application-specific decision and design.

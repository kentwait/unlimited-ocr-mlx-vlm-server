# Feature-Based TanStack Start Engineering Contract

This is the sole binding engineering contract for the repository. It applies to human
and AI contributors. Detailed reusable guidance lives under `arch_docs/`.

## Product Baseline

- Bun 1.x for installs, scripts, and tests (`bun.lock` is the lockfile). Vite
  remains the bundler — TanStack Start builds on it; bun replaces the Node
  runtime and package manager, not the build tool.
- TanStack Start in SPA mode, TanStack Router file routes, React 19, strict
  TypeScript.
- Tauri 2 desktop shell. The Rust command layer (`src-tauri`) is the
  filesystem boundary; the OCR FastAPI server is reached over HTTP. There is
  no Node server at runtime and no container image.
- Tailwind CSS v4 with semantic design tokens and a small ShadCN-compatible UI set.
- Zod runtime validation at untrusted boundaries.
- The `library` feature owns the three-pane PDF/markdown UI; sidecar files
  (`<stem>.md`, `<stem>.spans.jsonl`) live next to their PDFs on disk.

Do not add databases, authentication providers, global state libraries, query caches,
telemetry vendors, or cloud adapters without a concrete application requirement.

## Source Ownership

| Location                 | Owns                                                                                                                                                         | Must not own                                                         |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| `src/routes`             | File-route declarations, paths, loaders, search/param validation, guards, metadata, SSR options, route fallbacks, routing layouts, and raw `server.handlers` | Feature UI, database access, secrets, business rules                 |
| `src/features/<feature>` | Feature pages, components, hooks, schemas, server functions, server-only operations, and feature tests                                                       | URL registration, route-tree generation, another feature's internals |
| `src/shared/components`  | Proven cross-feature rendered UI, or deliberately curated template primitives, without feature knowledge                                                     | Business behavior, loaders, server-only imports                      |
| `src/shared/hooks`       | Proven cross-feature React behavior                                                                                                                          | Feature rules or route declarations                                  |
| `src/shared/types`       | Client-safe contracts with no single feature owner                                                                                                           | Feature-local or server-only types                                   |
| `src/lib`                | Focused app utilities and cross-cutting infrastructure glue                                                                                                  | Feature components, feature rules, catch-all service modules         |

Create folders only when code needs them. Keep code feature-local until cross-feature
reuse is real.

## Dependency Direction

Production imports must follow:

```text
routes -> features -> shared/lib
entrypoints -> routes/lib
shared/lib -> never features/routes
```

- Avoid feature-to-feature imports. Expose a narrow client-safe API only when a real
  dependency exists and keep the graph acyclic.
- Unsuffixed modules must be client-safe.
- `*.server.ts` may import databases, private SDKs, filesystem modules, and secrets.
- Components, hooks, route loaders, and client-safe barrels must never import
  `*.server.ts` directly.
- Do not re-export server-only values from a client-importable barrel.
- Do not hand-edit `src/routeTree.gen.ts`; regenerate it through dev or build tooling.

## TanStack Start Boundaries

- `getRouter()` returns a fresh router instance.
- `src/routes/__root.tsx` renders `HeadContent` and `Scripts`.
- `tanstackStart()` precedes the React Vite plugin.
- Loaders are isomorphic. They call client-safe server functions instead of databases,
  secrets, filesystem logic, or private SDKs.
- Use validated `createServerFn` wrappers for app-internal server work.
- Use GET for idempotent reads and POST for mutations and forms.
- Use route `server.handlers` for public APIs, webhooks, or exact `Request`/`Response`
  semantics.
- Keep static server-function imports. Do not dynamically import server functions.
- Private server functions and server routes authorize internally. Route guards provide
  navigation UX and are never the only data-security boundary.
- `src/start.ts` must retain server-function CSRF protection unless an accepted ADR
  records an equivalent alternative.

## TypeScript And React

- Keep strict mode, `noUncheckedIndexedAccess`, and `exactOptionalPropertyTypes`.
- Never use `any` in maintained source; narrow `unknown` values. Tool-owned generated files
  may contain framework-generated types that do not follow this rule.
- Prefer `type` over `interface` except framework declaration merging.
- Add explicit parameter and return types to public functions and components.
- Document exported application APIs with succinct TSDoc.
- Infer types from runtime schemas at I/O boundaries.
- Use named component exports and type-only imports.
- Use `getRouteApi()` in extracted feature pages rather than importing a route's
  `Route` object.
- Use semantic HTML, visible focus, correct labels, accessible status messages, and
  reduced-motion fallbacks.
- Use semantic tokens rather than raw palette colors in application components.

## Testing

- Co-locate feature unit and component tests with their feature.
- Keep route integration and source-boundary tests under `tests/routes`; never place
  test files under `src/routes`.
- Unit tests isolate external effects and cover happy paths, failures, and meaningful
  boundaries.
- Browser tests exercise the built application through the public UI and must not skip
  silently when prerequisites are absent.
- An in-process route test is not browser E2E, and a broad contract suite is not a
  smoke test.
- Run `bun run verify` before submission; run `bun scripts/ui-visual-check.mjs`
  (with `vite preview` serving `dist/client` and the OCR server reachable) for
  browser acceptance. Run `cargo check` in `src-tauri/` when changing Rust code.

## Specifications And Decisions

- Reusable template guidance and decisions live under `arch_docs/`.
- Application requirements, designs, and decisions live under `docs/`.
- The master PRD is `Vision` and never authorizes implementation by itself.
- Significant features, public contracts, authentication, persistence, deployment,
  security boundaries, migrations, and cross-runtime changes require a normative
  focused PRD and normative owning technical design.
- Routine fixes, maintenance, and isolated internal improvements may use ordinary
  issue and review flow when they do not change product or architecture contracts.
- Record durable reusable architecture decisions in `arch_docs/adr/` and durable
  application decisions in `docs/adr/`. New unresolved ADRs begin as `Proposed`.
- A technical design elaborates product requirements but must not redefine them.

## Self-Audit

- [ ] Code is owned by the correct route, feature, shared, or utility location.
- [ ] Imports follow the directed graph and client code has no server-only dependency.
- [ ] Application-owned untrusted inputs and environment values are runtime validated.
- [ ] Private data authorization occurs at the server boundary.
- [ ] Routes remain thin and extracted pages use `getRouteApi()`.
- [ ] New shared abstractions have demonstrated cross-feature reuse or a deliberate
      template-baseline purpose.
- [ ] Tests match the changed risk and all documented verification commands pass.
- [ ] Significant work is authorized by current product and technical contracts.
- [ ] Reusable and application documentation remain in their owning trees.

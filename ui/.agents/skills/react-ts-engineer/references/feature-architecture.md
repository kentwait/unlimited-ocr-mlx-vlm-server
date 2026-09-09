# Feature-Based React Architecture

Use this reference when scaffolding a React app, adding or moving a business
feature, deciding whether code is reusable, or reviewing module ownership and
dependency direction.

## Default Structure

Organize application code by business capability first. Create folders only
when a feature needs them; do not add empty architecture folders preemptively.

```text
src/
  features/
    jobs/
      pages/                    # Route-level feature views
        jobs-page.tsx
      components/               # Feature-local UI
        job-card.tsx
        job-card.test.tsx       # Co-located component test
        job-grid.tsx
      hooks/                    # Feature-owned React behavior
        use-jobs.ts
      jobs.service.ts           # Feature data access
      jobs.schema.ts            # Runtime schemas and inferred contracts
  shared/
    components/                 # Proven feature-agnostic rendered UI
    hooks/                      # Hooks with no feature owner
    types/                      # Client-safe cross-feature contracts
  lib/                          # App utilities and infrastructure glue
  routes/                       # Paths, guards, layouts, route registration
  styles/                       # Tokens, generated variables, Tailwind entry
  App.tsx
scripts/
  generate-tokens.ts
```

A feature contains one major business capability and its pages, components,
hooks, data access, contracts, state, and tests. Subfolders are local
organizational aids inside that slice, not global horizontal layers.

## Ownership Rules

| Location | Owns | Must not own |
| --- | --- | --- |
| `src/routes` | Paths, route registration, guards, route layouts, and route-specific behavior | Feature business UI, feature hooks, or data-access implementations |
| `src/features/<feature>` | Feature pages, components, hooks, services, contracts, state, and tests | Another feature's internals or generic app utilities |
| `src/shared/components` | Proven cross-feature UI primitives and compositions with no feature knowledge | Feature behavior, business data access, or speculative abstractions |
| `src/shared/hooks` | Reusable React behavior with no feature owner | Feature business rules |
| `src/shared/types` | Client-safe contracts with no single feature owner | Types that still belong to one feature |
| `src/lib` | Formatting, logging, configuration, and infrastructure glue | React feature components or a catch-all service layer |

## Reuse and Promotion

- Start code in the feature that owns its language and behavior.
- Reuse focused primitives, composed controls, and feature sections through
  component composition; visual complexity does not determine folder location.
- Promote UI to `src/shared/components` only after cross-feature reuse is real.
- Before promotion, remove feature language, business behavior, and data access
  from the shared API.
- Keep reusable non-rendered React behavior in `src/shared/hooks`; keep ordinary
  app utilities in `src/lib`.
- Prefer focused modules such as `format-date.ts` or `logger.ts` over a generic
  dumping-ground `utils.ts`.

## Dependency Direction

Prefer this direction:

```text
routes -> features -> shared/lib
shared/lib -> never features or routes
```

Avoid feature-to-feature imports. If collaboration is genuinely required,
expose a narrow public API from the owning feature, keep it client-safe where
needed, and keep the dependency graph acyclic.

## Tests and Migration

Co-locate React unit and component tests with their feature modules. Keep
broader route integration and end-to-end suites in explicit test directories
when that makes the tested boundary clearer.

Use this structure by default for greenfield apps and new features. When an
existing app has another established structure, preserve its conventions unless
the user requests an explicit migration. Migrate one complete feature at a time
rather than creating parallel global and feature-based homes for new code.

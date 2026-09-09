---
name: react-ts-engineer
description: Engineer React 19 applications with TypeScript, Vite, and feature-based architecture. Use when building, scaffolding, or refactoring React frontend applications. Extends ts-coder, inherits its Node.js and pnpm baseline, and overrides framework-agnostic architecture and testing defaults for React feature structure, component composition, browser concerns, jsdom, and co-located component tests. Combine with ts-qa-engineer for test strategy and react-ts-ui-designer for visual implementation. TanStack Start projects use tanstack-start-engineer's routing and server-boundary rules.
---

# React TypeScript Engineer

## Inheritance and Precedence

| Domain | Governing skill |
|---|---|
| Typing, documentation, linting, package management, and general imports | **ts-coder**, except for framework-specific rules explicitly stated here |
| React architecture and browser runtime concerns | **react-ts-engineer** |
| Test strategy, mocks, fixtures, and coverage | **ts-qa-engineer** |
| React test environment and test placement | **react-ts-engineer** |
| Visual styling and accessibility | **react-ts-ui-designer** |
| Routing, server boundaries, route-coupled data access, and deployment in TanStack Start apps | **tanstack-start-engineer** |

This skill extends **ts-coder** and otherwise inherits its Node.js LTS, pnpm,
strict typing, documentation, linting, and general coding rules.

Treat code blocks as focused excerpts. In generated code, add the explicit
return types and TSDoc required by **ts-coder**. Examples may omit them only
for brevity and do not override generated-code requirements.

## Quick Reference

| Task | Command |
|---|---|
| Dev server | `pnpm run dev` |
| Build | `pnpm run build` |
| Preview build | `pnpm run preview` |
| Add dependency | `pnpm add <package>` |
| Add dev dependency | `pnpm add --save-dev <package>` |
| Lint & fix | `pnpm run lint --fix` |
| Run tests | `pnpm test` |
| Generate tokens | `pnpm run generate:tokens` |

## Project Structure

Load **[feature-architecture.md](references/feature-architecture.md)** when
scaffolding an app, adding or moving a feature, deciding whether code is
shared, or reviewing dependency direction. It defines the default tree,
ownership boundaries, promotion rules, and migration guidance.

When refactoring an existing non-feature-based project, incrementally migrate
one feature slice at a time. Do not restructure the entire `src` tree in a
single step. Identify one business capability, extract it to
`src/features/<feature>`, fix imports, and verify tests pass before proceeding
to the next feature.

## Feature-Based Architecture

Organize application code by business capability first. Keep pages, components,
hooks, data access, types, and tests in the owning `src/features/<feature>`
slice.

Use `src/shared/components` for rendered UI only after it has genuine
cross-feature reuse and no feature knowledge. Use `src/shared/hooks` and
`src/shared/types` under the same rule. Put app utilities in `src/lib`.

Prefer this dependency direction:

```text
routes -> features -> shared/lib
shared/lib -> never features or routes
```

Avoid feature-to-feature imports and speculative shared abstractions.

### Reusable Components

Retain reusable composition principles without encoding visual complexity as
global folder tiers:

- **UI primitives** are single-purpose, feature-agnostic controls such as
  buttons, inputs, badges, and cards. Put proven shared primitives in
  `src/shared/components`.
- **Compositions** combine primitives into reusable units. Keep them in a
  feature while they express feature language or behavior. Promote only when
  the component is actively used by two or more distinct features and contains
  no feature-specific logic.
- **Sections** compose feature UI and may own local state or data interaction.
  Keep them in the owning feature even when they reuse shared primitives.
- **Pages** compose feature sections for route endpoints. Keep routing config in
  `src/routes` and page UI in the owning feature.

Choose a component's location by business ownership and reuse, not visual
complexity. Prefer small, focused components with clear props and composition
over monolithic feature views.

### Shared Primitive Example

Shared primitives contain no business logic.

- In React 19, accept `ref` as an ordinary prop when exposing a DOM node
- Named exports only
- Accept `className` prop for composition
- Add `data-slot` attribute

```tsx
import * as React from "react";

type ButtonProps = React.ComponentPropsWithRef<"button">;

export function Button({ ref, ...props }: ButtonProps) {
  return <button ref={ref} data-slot="button" {...props} />;
}
```

Apply **react-ts-ui-designer** for CVA variants, tokens, classes, and visual
states.

### Feature Composition Example

Feature components may combine shared primitives. Use named function exports
and declare the props interface above the component.

```tsx
import { Button } from "@/shared/components/button";
import { Card } from "@/shared/components/card";
import type { Job } from "../jobs.schema";

interface JobCardProps {
  job: Job;
  onApply?: (id: string) => void;
}

/** Displays job summary with apply action. */
export function JobCard({ job, onApply }: JobCardProps) {
  return (
    <Card data-slot="job-card">
      <h3 className="text-lg font-semibold">{job.title}</h3>
      <p className="text-muted-foreground">{job.description}</p>
      <Button variant="outline" onClick={() => onApply?.(job.id)}>
        Apply
      </Button>
    </Card>
  );
}
```

### Feature Section Example

Feature sections may manage local state or use feature-owned data access.

```tsx
import { JobCard } from "./job-card";
import { useJobs } from "../hooks/use-jobs";

/** Grid of job postings with loading state. */
export function JobGrid() {
  const { jobs, loading } = useJobs();

  if (loading) return <div data-slot="job-grid-skeleton">Loading…</div>;

  return (
    <section data-slot="job-grid" className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {jobs.map((job) => <JobCard key={job.id} job={job} />)}
    </section>
  );
}
```

### Route Layouts

Page-level shells wrapping `<Outlet />`. Handle navigation, sidebars, footers.

```tsx
import { Outlet } from "react-router";
import { Header } from "@/shared/components/header";
import { Sidebar } from "@/features/dashboard/components/sidebar";

/** Authenticated layout with sidebar navigation. */
export function DashboardLayout() {
  return (
    <div data-slot="dashboard-layout" className="flex min-h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Header />
        <main className="flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

### Feature Pages

Full page compositions. Default exports. Organized by access level.

```tsx
import { Hero } from "../components/hero";
import { JobGrid } from "../components/job-grid";

/** Public landing page. */
export default function Landing() {
  return (
    <>
      <Hero />
      <JobGrid />
    </>
  );
}
```

### Placement Selection

| Need | Location |
|---|---|
| UI specific to one business capability | `src/features/<feature>/components` |
| Page UI for a feature route | `src/features/<feature>/pages` |
| Hook, type, or service with a clear feature owner | The owning feature slice |
| Proven feature-agnostic rendered UI | `src/shared/components` |
| Proven feature-agnostic hook or type | `src/shared/hooks` or `src/shared/types` |
| Reusable app utility or infrastructure glue | `src/lib` |
| Route paths, guards, layouts, and route registration | `src/routes` |

## Component Patterns

### Props Interface

Declare props above the component. Use `interface` for component props that add
fields to or combine DOM attributes; this is a narrow React-specific override
of **ts-coder**'s general `type` preference. Use a `type` alias when props are
exactly another type, and continue to use `type` for ordinary data models and
unions.

```tsx
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}
```

### Generic Components

```tsx
interface ListProps<T> {
  items: T[];
  renderItem: (item: T) => React.ReactNode;
  keyExtractor: (item: T) => string;
}

/** Typed list renderer. */
export function List<T>({ items, renderItem, keyExtractor }: ListProps<T>) {
  return (
    <ul>{items.map((item) => <li key={keyExtractor(item)}>{renderItem(item)}</li>)}</ul>
  );
}
```

### Type-Only Imports

```tsx
import type { Job } from "@/features/jobs/jobs.schema";
import type { VariantProps } from "class-variance-authority";
import { Button } from "@/shared/components/button";
```

Always use `type` for imports used only as types. Use `@/` path aliases by
default. A framework-specific skill may override import conventions for its
generated files, build tooling, or established project structure.

## React 19 Patterns

Load **[react-19-patterns.md](references/react-19-patterns.md)** when implementing
Actions, optimistic updates, transitions, or promise reading with Suspense. It
contains API selection guidance and focused examples for `useActionState`,
`useOptimistic`, `useTransition`, and `use`.

## Custom Hooks

Keep feature-owned hooks in `src/features/<feature>/hooks`. Promote a hook to
`src/shared/hooks` only when it has no feature knowledge and genuine
cross-feature use. Prefix with `use`, annotate its return type, and add TSDoc.

```tsx
/**
 * Debounce a value by the given delay.
 * @param value - Value to debounce.
 * @param delay - Debounce delay in milliseconds.
 * @returns Debounced value.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = React.useState(value);

  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
```

## State Management

| Pattern | When |
|---|---|
| `useState` | Simple local state |
| `useReducer` | Complex local state with multiple transitions |
| Context + Provider | Shared state across a subtree (auth, theme) |
| `useActionState` | Form submission state |
| `useOptimistic` | Instant UI feedback before server confirmation |

### Context Provider Pattern

In React 19, render the context object directly as the provider:
`<AuthContext value={value}>`. Read it with `React.use(AuthContext)` or
`React.useContext(AuthContext)`. Keep the context default nullable when absence
is invalid, and expose a custom hook that throws a clear error outside the
provider.

## Data Fetching & Services

### Feature Service Modules

Keep data access with its owning feature rather than creating a global
`src/services` layer.

```tsx
import { JobsResponseSchema, type JobsResponse } from "./jobs.schema";
import { env } from "@/lib/env.client";

/** Fetch paginated job listings. */
export async function getJobs(page = 1): Promise<JobsResponse> {
  const response = await fetch(`${env.VITE_API_URL}/jobs?page=${page}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch jobs: ${response.status}`);
  }

  const payload: unknown = await response.json();
  return JobsResponseSchema.parse(payload);
}
```

### Feature Schemas and Types

Keep feature contracts in the feature. Promote only client-safe contracts with
no single feature owner to `src/shared/types`.

```tsx
import { z } from "zod";

export const JobSchema = z.object({
  id: z.string(),
  title: z.string().min(1),
  description: z.string(),
  status: z.enum(["draft", "published", "archived"]),
  createdAt: z.coerce.date(),
});

export const JobsResponseSchema = z.object({
  data: z.array(JobSchema),
  error: z.string().optional(),
  meta: z.object({ page: z.number(), total: z.number() }).optional(),
});

/** API response wrapper. */
export type JobsResponse = z.infer<typeof JobsResponseSchema>;

/** Job posting entity. */
export type Job = z.infer<typeof JobSchema>;
```

### Environment Variables

```tsx
import { z } from "zod";

const ClientEnvSchema = z.object({
  VITE_API_URL: z.string().url(),
  VITE_APP_NAME: z.string().min(1),
});

export const env = ClientEnvSchema.parse(import.meta.env);
```

## Routing — React Router v8

Organize routes by access level in `src/routes/{public,user,admin}.tsx`. Combine in `src/routes/index.tsx`:

```tsx
import type { RouteObject } from "react-router";

// src/routes/public.tsx — unauthenticated routes
export const publicRoutes: RouteObject[] = [{ path: "/", element: <Landing /> }];

// src/routes/user.tsx — wrap in layout with <Outlet/>
export const userRoutes: RouteObject[] = [
  { element: <DashboardLayout />, children: [{ path: "/dashboard", element: <Dashboard /> }] },
];

// src/routes/index.tsx — combine all
export const routes: RouteObject[] = [...publicRoutes, ...userRoutes, ...adminRoutes];
```

## Error Handling

### Error Boundary

```tsx
export class ErrorBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  render() { return this.state.hasError ? this.props.fallback : this.props.children; }
}
```

### Async Error Handling

Wrap service calls in try/catch. Surface errors via state. Narrow `unknown` errors with `err instanceof Error`.

## Performance

| Technique | When |
|---|---|
| React Compiler | Default memoization path for new code when supported by the app's toolchain |
| `React.memo(Component)` | A profiled component is expensive and React Compiler is unavailable or needs an explicit escape hatch |
| `useMemo(() => compute(), [deps])` | A profiled calculation is expensive or a value needs explicit identity control |
| `useCallback(fn, [deps])` | A function needs explicit identity control, such as a dependency or prop of a manually memoized component |
| `React.lazy(() => import(...))` | Code-split routes or heavy components |

Do not add manual memoization by default. Preserve existing memoization unless
profiling and tests support removing it.

### Lazy Routes

```tsx
import type { RouteObject } from "react-router";

const AdminPanel = React.lazy(() => import("@/features/admin/pages/admin-panel"));

const adminRoute: RouteObject = {
  path: "/admin",
  element: <React.Suspense fallback={<Skeleton />}><AdminPanel /></React.Suspense>,
};
```

## Testing

Use Vitest with jsdom environment. Co-locate test files: `component.test.tsx` next to `component.tsx`.

Apply **ts-qa-engineer** for test strategy, mocking, fixtures, coverage, and
async patterns. This skill overrides its default Node test environment and test
placement for React unit/component tests; keep broader integration and e2e
suites in explicit test directories when appropriate.

## File Locations

| Type | Location |
|---|---|
| Feature components | `src/features/<feature>/components/[name].tsx` |
| Feature pages | `src/features/<feature>/pages/[name]-page.tsx` |
| Feature hooks | `src/features/<feature>/hooks/use-[name].ts` |
| Feature services | `src/features/<feature>/<feature>.service.ts` |
| Feature schemas/types | `src/features/<feature>/<feature>.schema.ts` |
| Shared components | `src/shared/components/[name].tsx` |
| Shared hooks | `src/shared/hooks/use-[name].ts` |
| Shared types | `src/shared/types/[name].ts` |
| `cn()` utility | `src/lib/cn.ts` |
| Design tokens | `src/styles/tokens.ts` |
| Generated CSS tokens | `src/styles/tokens.css` |
| Tailwind entry | `src/styles/index.css` |
| Route configs | `src/routes/{public,user,admin}.tsx` |
| Feature providers | `src/features/<feature>/[name]-context.tsx` |
| Token generator | `scripts/generate-tokens.ts` |

## Completion Checklist

- [ ] Exported functions, components, hooks, and types have TSDoc.
- [ ] Props are declared above the component with descriptive property names.
- [ ] Type-only imports use `import type { X }`.
- [ ] Imports use the `@/` alias unless a framework-specific skill overrides it.
- [ ] Component root elements have a `data-slot` attribute.
- [ ] Class names are merged with `cn()`.
- [ ] API, user-input, file, and environment boundaries use runtime schemas.
- [ ] Async UI sections have error boundaries.
- [ ] Lazy-loaded components have Suspense boundaries.

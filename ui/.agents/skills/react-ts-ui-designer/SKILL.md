---
name: react-ts-ui-designer
description: Design and implement the visual layer of React 19 interfaces with TypeScript, design tokens, Tailwind CSS v4, feature-based placement, and reusable component composition. Use for visual component implementation, mockups, styling, theming, layout, accessibility, animation, responsive behavior, and UI states. Extends ts-coder and composes with react-ts-engineer and applicable framework skills.
---

# React TypeScript UI Designer

## Inheritance and Precedence

This skill extends **ts-coder** and composes with **react-ts-engineer**. Inherit
Node.js LTS, pnpm, and strict TypeScript from the base skill.

| Domain | Governing skill |
|---|---|
| Node.js, package manager, and TypeScript conventions | **ts-coder** |
| Feature placement and component architecture | Applicable framework skill, otherwise **react-ts-engineer** |
| State and form-state selection | Applicable framework skill, otherwise **react-ts-engineer** |
| Routing and server boundaries | Applicable framework skill, otherwise **react-ts-engineer** |
| Visual implementation, styling, and design tokens | **react-ts-ui-designer** |
| Accessibility, animation, responsive behavior, and visual states | **react-ts-ui-designer** |

## Quick Reference

| Item | Location |
|---|---|
| Design tokens (source of truth) | `src/styles/tokens.ts` |
| Generated CSS variables | `src/styles/tokens.css` |
| Tailwind entry / `@theme` bridge | `src/styles/index.css` |
| Token generator script | `scripts/generate-tokens.ts` |
| `cn()` utility | `src/lib/cn.ts` |
| Feature-owned UI | `src/features/<feature>/{components,pages}/[name].tsx` |
| Proven cross-feature UI | `src/shared/components/[name].tsx` |
| Regenerate tokens command | `pnpm run generate:tokens` |

## Libraries

- **ShadCN/ui + Radix UI** — Default foundation for all UI elements. Check for
  an existing ShadCN component or Radix primitive before building from scratch.
  Extend via CVA variants, not by forking internals. If neither satisfies the
  requirement, build a semantic HTML primitive with the `cn()` + CVA pattern,
  keep it in the owning feature, and document it for possible shared promotion.
- **@tanstack/react-table** — Use for all table and data-grid implementations.
  Configure sorting, filtering, pagination, and row selection as needed. Style
  with ShadCN `<Table>` components and semantic tokens.
- **React Hook Form** — When selected by the app's React or framework
  architecture, integrate it with ShadCN form components and present validation
  states and errors accessibly. See the ownership table above.
- **lucide-react** — Sole icon library. Set explicit `h-4 w-4` and add
  `aria-hidden="true"` to decorative icons. When an icon is a button's only
  content, put a descriptive `aria-label` on the button.
- **Motion for React** — Install `motion` and import APIs from `motion/react`.
  Use it only when animation involves multiple elements,
  sequencing, shared layout, or mount/unmount awareness. Use CSS for a
  single-property transition on one element. Add motion only when it delivers
  clear UX value, and respect reduced-motion preferences with `MotionConfig` or
  `useReducedMotion`.

## Performance & UX Tradeoffs

Balance interface richness against load time. A beautiful page that loads
slowly is worse than a clean page that loads fast.

- Lazy-load heavy components with `React.lazy()` + `Suspense`
- Code-split by route; keep initial bundle lean
- Prefer tree-shakeable imports over barrel exports
- Use skeleton loaders and progressive enhancement over blocking renders
- Before adding a library for a visual effect, ask if CSS alone achieves 80% of the result
- Use `loading="lazy"` on offscreen images, prefer WebP/AVIF, and use responsive
  `srcSet`; do not lazy-load likely first-viewport content

## Design Token Pipeline

**`tokens.ts` is the single source of truth.** Never hardcode colors, spacing,
radii, shadows, or timing values. If a value does not have a token, create one
first.

Pipeline: `tokens.ts` → `generate-tokens.ts` → `tokens.css` → `@theme` in `index.css` → Tailwind utilities.

For Vite, install Tailwind v4 with `pnpm add --save-dev tailwindcss @tailwindcss/vite`
and register `@tailwindcss/vite`. If the project uses PostCSS instead, install
`tailwindcss @tailwindcss/postcss postcss` as dev dependencies and register
`@tailwindcss/postcss`. Choose one integration; do not configure both. In CSS,
use `@import "tailwindcss"`, not `@tailwind` directives.

Token structure in `src/styles/tokens.ts` (read file for full values):

```ts
export const colors = {
  background: "oklch(100% 0 0)",
  foreground: "oklch(14.5% 0 0)",
  primary: "oklch(20.5% 0 0)",
  "primary-foreground": "oklch(98.5% 0 0)",
  // ... semantic pairs: secondary, muted, accent, destructive, border, input, ring, card
} as const;

export const darkColors = { /* dark-mode overrides for each color */ } as const;
export const spacing = { 0: "0px", 1: "0.25rem", 2: "0.5rem", /* ... */ 24: "6rem" } as const;
export const radius = { sm: "0.25rem", md: "0.375rem", lg: "0.5rem", xl: "0.75rem", "2xl": "1rem", full: "9999px" } as const;
export const fontSize = { xs: "0.75rem", sm: "0.875rem", base: "1rem", /* ... */ "4xl": "2.25rem" } as const;
export const shadows = { sm: "...", md: "...", lg: "...", xl: "..." } as const;
export const zIndex = { dropdown: "50", sticky: "100", overlay: "200", modal: "300", popover: "400", toast: "500" } as const;
export const durations = { fast: "150ms", normal: "200ms", slow: "300ms", slower: "500ms" } as const;
```

After editing `tokens.ts`, run `pnpm run generate:tokens` to regenerate
`tokens.css`. Map supported Tailwind namespaces such as `--color-*`,
`--spacing-*`, `--radius-*`, and `--shadow-*` through `@theme`. Emit duration
and z-index tokens as regular CSS variables and consume them with Tailwind's
CSS-variable utility syntax. Read `src/styles/index.css` for the full mapping.

### Token Access

| Context | Method |
|---|---|
| Tailwind classes | `bg-primary`, `rounded-lg`, `duration-(--duration-fast)`, `z-(--z-sticky)` |
| Raw CSS | `color: var(--color-primary);` |
| JS (charts, canvas) | `import { colors } from "@/styles/tokens"` |

### Semantic Color Pairs

| Pair | Usage |
|---|---|
| `bg-background` / `text-foreground` | Page base |
| `bg-primary` / `text-primary-foreground` | Primary actions |
| `bg-secondary` / `text-secondary-foreground` | Secondary actions |
| `bg-muted` / `text-muted-foreground` | De-emphasized content |
| `bg-accent` / `text-accent-foreground` | Highlights |
| `bg-destructive` / `text-destructive-foreground` | Danger actions |
| `bg-card` / `text-card-foreground` | Card surfaces |
| `border-border` / `border-input` | Borders |

## Styling

### Dark Mode

Apply dark-mode overrides using Tailwind's `dark:` variant. The `darkColors`
tokens are mapped to the same CSS variable names inside a `.dark` class selector
in `tokens.css`. Never use `prefers-color-scheme` directly in components; rely
solely on the `.dark` class toggled at the `<html>` element.

Override Tailwind's default media-query-driven variant in `index.css`:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

### cn() + CVA Pattern

Use `cn()` from `@/lib/cn` for all className merging. Define component variants with `cva`:

```tsx
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground",
        secondary: "bg-secondary text-secondary-foreground",
        destructive: "bg-destructive text-destructive-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  ref?: React.Ref<HTMLSpanElement>;
}

export function Badge({ className, variant, ref, ...props }: BadgeProps) {
  return (
    <span ref={ref} data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}
```

### Responsive Design

Mobile-first. Breakpoints: `sm` (640), `md` (768), `lg` (1024), `xl` (1280), `2xl` (1536).

```tsx
<div className={cn("flex flex-col gap-4", "md:flex-row md:gap-6", "lg:gap-8")} />
```

## Visual Composition

See ownership table above. Apply visual rules according to component
responsibility, without creating global folders based on visual complexity.

| Responsibility | Visual Rules |
|---|---|
| UI primitives | Expose `className`; semantic tokens only; `transition-colors` for interactive states; token-backed sizing |
| Reusable compositions | Use focused internal layout; avoid outer margins; forward `className` and relevant state |
| Feature sections | Use grid/flex layout, token-backed section spacing, responsive breakpoints, and loading/empty/error states |
| Route layouts | Use stable `min-h-screen` regions; make primary content flexible; collapse navigation responsively |
| Feature pages | Compose focused sections; keep page-level styling intentional and minimal |

Keep feature-specific primitives and compositions in their owning feature.
Promote UI to `src/shared/components` only when two or more distinct features
consume the same component and it has been explicitly approved for sharing.
Remove feature language, data access, and business behavior from the shared API.
Reuse may come from focused primitives, composed controls, or larger sections;
reuse does not require a directory tier.

Use `data-slot` on component root elements and significant sub-parts for identification.

## Layout Patterns

```tsx
// Sidebar + Content
<div className="flex min-h-screen">
  <aside className="w-64 border-r bg-card p-4 max-md:hidden">{nav}</aside>
  <main className="flex-1 p-6">{children}</main>
</div>;

// Header + Main + Footer
<div className="flex min-h-screen flex-col">
  <header className="sticky top-0 z-(--z-sticky) border-b bg-background px-6 py-3">{nav}</header>
  <main className="flex-1 p-6">{children}</main>
  <footer className="border-t px-6 py-4 text-muted-foreground">{footer}</footer>
</div>;

// Dashboard Grid
<div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">{cards}</div>;
```

## Animation

Use CSS transitions for simple state changes and Motion for React for complex
orchestration.

| Scenario | Approach |
|---|---|
| Hover/focus color | CSS `transition-colors duration-(--duration-fast)` |
| Button press scale | CSS `transition-transform duration-(--duration-normal)` |
| Page/route transition | Motion for React |
| List stagger, drag/reorder | Motion for React |
| Modal enter/exit | Motion `AnimatePresence` |
| Shared layout animation | Motion `layoutId` |

```tsx
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { durations } from "@/styles/tokens";

const normalDurationSeconds = Number.parseFloat(durations.normal) / 1000;

// CSS transition — simple states
<div className="transition-colors duration-(--duration-fast) hover:bg-accent motion-reduce:duration-0" />;

// Motion — orchestrated entry with site-wide reduced-motion handling
<MotionConfig reducedMotion="user">
  <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: normalDurationSeconds }} />
</MotionConfig>;

// Motion — presence-aware exit
<AnimatePresence mode="wait">
  {isVisible && <motion.div key="panel" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />}
</AnimatePresence>;
```

Timing variables: `--duration-fast` (150ms), `--duration-normal` (200ms),
`--duration-slow` (300ms), and `--duration-slower` (500ms).

## Accessibility

- Use semantic HTML elements (`<button>`, `<a>`, `<nav>`, `<main>`, landmarks)
- `aria-label` on icon-only buttons; `aria-hidden="true"` on decorative icons
- `aria-busy` on loading states; `aria-expanded` + `aria-controls` on expandable sections
- Focus rings: `focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none`
- Trap focus in modals; return focus to trigger on close
- WCAG 2.2 AA contrast: 4.5:1 normal text and 3:1 large text; verify semantic
  token pairs rather than assuming they comply
- CSS transitions use a `motion-reduce:` fallback such as `duration-0`
- Motion trees use `<MotionConfig reducedMotion="user">`; use
  `useReducedMotion` when an animation needs a custom alternative

## Completion Checklist

For each applicable component, verify:

- [ ] The root element has a `data-slot` attribute.
- [ ] Class names are merged with `cn()`.
- [ ] Colors use semantic tokens rather than hardcoded values.
- [ ] Spacing and radii use tokens rather than arbitrary pixels.
- [ ] Interactive elements use `focus-visible:ring-2 focus-visible:ring-ring`.
- [ ] CSS animations and Motion components respect reduced-motion preferences.
- [ ] Layout components use responsive breakpoints.
- [ ] New visual values are added to `tokens.ts` first.

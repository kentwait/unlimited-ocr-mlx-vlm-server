---
name: ts-coder
description: Base TypeScript engineering conventions for clean, maintainable libraries, CLIs, scripts, and backend services. Use directly for framework-agnostic TypeScript and combine with ts-qa-engineer, react-ts-engineer, react-ts-ui-designer, or tanstack-start-engineer for specialized work. Covers Node.js and pnpm tooling, project setup, strict typing, documentation, linting, and basic testing; specialized skills inherit these rules and override them only within their stated ownership.
---

# TypeScript Coder

## Inheritance and Precedence

This is the base skill for TypeScript work. Specialized TypeScript skills inherit
these conventions unless they explicitly state an override for the domain they
own. Resolve conflicts in favor of the most specific applicable skill.

| Domain | Governing skill |
|---|---|
| General TypeScript, Node.js, pnpm, typing, documentation, and linting | **ts-coder** |
| Test strategy, structure, mocks, and fixtures | **ts-qa-engineer** |
| React architecture, composition, browser concerns, and React test placement/environment | **react-ts-engineer** |
| Visual implementation, styling, tokens, accessibility, and responsive behavior | **react-ts-ui-designer** |
| TanStack Start routing, data loading, server boundaries, and deployment | **tanstack-start-engineer** |

Node.js LTS and pnpm are repository-wide TypeScript requirements and are not
overridden by specialized skills.

## Runtime & Tooling

- Follow a repository's supported pinned **TypeScript** version and **Node.js
  LTS** line. For a greenfield project, use the latest stable TypeScript version
  supported by the selected framework, linter, and build tool, plus the current
  active Node.js LTS line. Do not move an existing project between major
  versions without checking peer ranges and migration guidance.
- Require **`pnpm`** as the package manager and script runner; do not substitute another tool.

| Task | Command |
|---|---|
| Init project | `pnpm init` |
| Run a compiled file | `node <file.js>` |
| Run a package.json script | `pnpm run <script>` |
| Add a dependency | `pnpm add <package>` |
| Add a dev dependency | `pnpm add --save-dev <package>` |
| Run an executable | `pnpm exec <command>` |
| Install dependencies | `pnpm install` |
| Lint & auto-fix | `pnpm run lint --fix` |
| Run tests | `pnpm test` |

## Project Setup

### Initialization

```bash
mkdir <project-name>
cd <project-name>
pnpm init
```

### package.json

Set ESM-first:

```json
{
  "type": "module"
}
```

Declare Node.js and pnpm requirements in `package.json`, place dev tools
(TypeScript, ESLint, etc.) under `devDependencies`, and run `pnpm install`
after modifying dependencies. For a greenfield project, use the current active
LTS major; this example uses Node.js 24 and pnpm 11:

```json
{
  "engines": {
    "node": ">=24 <25"
  },
  "packageManager": "pnpm@11.14.0"
}
```

### tsconfig.json

Use strict mode with modern defaults:

```json
{
  "compilerOptions": {
    "target": "ES2024",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist",
    "declaration": true
  },
  "include": ["src"]
}
```

### ESLint (Flat Config)

```bash
pnpm add --save-dev eslint @eslint/js typescript-eslint
```

```javascript
// eslint.config.js
import eslint from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import tseslint from "typescript-eslint";

export default defineConfig(
  globalIgnores(["dist/**", "coverage/**"]),
  {
    files: ["**/*.{ts,tsx,mts,cts}"],
    extends: [eslint.configs.recommended, tseslint.configs.strictTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  }
);
```

Before selecting a TypeScript version, inspect the installed framework and
lint-tool peer ranges. Do not assume the newest TypeScript release is already
supported by `typescript-eslint`.

Add lint and test scripts to `package.json`:

```json
{
  "scripts": {
    "lint": "eslint .",
    "test": "vitest run"
  }
}
```

## Coding Conventions

### Type Annotations

Annotate all function parameters and return types:

```typescript
function processItems(items: string[], limit: number): string[] {
  return items.slice(0, limit);
}
```

### Types vs Interfaces

Prefer `type` over `interface` unless declaration merging is needed:

```typescript
// Preferred
type User = {
  id: string;
  name: string;
  email: string;
};

// Use interface only when merging is required
interface WindowExtensions {
  analyticsId: string;
}
```

### Strict Typing Rules

- **Never use `any`**. Use `unknown` and narrow with type guards.
- **Use `satisfies`** to validate type conformance while preserving inference.
- **Prefer literal union types** over enums: `type Status = "active" | "inactive"`.
- Use `parameter?: X` when callers may omit a function argument. Use
  `X | undefined` when a present value may be absent, such as a missing lookup
  result. Use `X | null` only when explicitly representing an intentional empty
  value at an IO boundary or when interoperating with APIs that return null.

### Runtime Validation at IO Boundaries

Validate untrusted data at IO boundaries such as API responses, user input,
file reads, and environment variables. Use the repository's established runtime
schema library; default to Zod in greenfield projects. Infer static types from
schemas when the library supports it:

```typescript
import { z } from "zod";

const UserSchema = z.object({
  id: z.string().uuid(),
  name: z.string().min(1),
  email: z.string().email(),
});

type User = z.infer<typeof UserSchema>;

function parseUser(data: unknown): User {
  return UserSchema.parse(data);
}
```

### Documentation

Write **TSDoc** for every public function, class, method, and type:

```typescript
/**
 * Fetch records from a paginated API endpoint.
 *
 * @param endpoint - Full URL of the API endpoint.
 * @param limit - Maximum number of records to return.
 * @returns List of record objects keyed by field name.
 * @throws {ConnectionError} If the endpoint is unreachable.
 */
function fetchRecords(endpoint: string, limit: number = 100): Promise<Record<string, string>[]> {
  // ...
}
```

### Comments

Write self-documenting code. Add inline comments only for:

- Novel algorithms or non-obvious logic.
- Workarounds, hacks, or subtle edge-case handling.
- Business-rule explanations that cannot be expressed through naming alone.

Each comment should explain **why**, not restate what the code does.

## Linting

Before presenting code to the user, lint it:

```bash
pnpm run lint --fix
```

If unfixable issues remain, resolve them manually and re-run until clean.

If the linting environment is unavailable, manually verify that the code
conforms to the ESLint rules configured above (`no any`, strict type-checked
rules) and note that linting should be run before committing.

## Testing

Use **Vitest** with Node.js and run it through pnpm.

```bash
pnpm add --save-dev vitest
```

For comprehensive testing directives — mocking strategies, fixture design,
parameterized tests, edge-case patterns, async testing, and the three-tier
testing strategy (unit / integration / e2e) — apply the **ts-qa-engineer**
skill.

### Running Tests

```bash
pnpm test
```

## Handling Unfamiliar APIs

When unsure about a package's interface, inspect type definitions rather than guessing:

1. **Read `.d.ts` files** directly: `node_modules/<pkg>/dist/index.d.ts` or `node_modules/@types/<pkg>/index.d.ts`.
2. **Use utility types** to explore at the type level:

```typescript
// Extract a function's return type
type Result = ReturnType<typeof someFunction>;

// Extract a function's parameter types
type Params = Parameters<typeof someFunction>;

// Get keys of an object type
type Keys = keyof SomeType;
```

3. **Use the editor's go-to-definition** to inspect signatures and overloads.

Use the output to correct the code rather than relying on potentially outdated training data.

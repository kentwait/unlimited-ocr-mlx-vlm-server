---
name: ts-qa-engineer
description: Specialized TypeScript testing guidance using Vitest on Node.js. Use when writing, reviewing, or improving tests for libraries, CLIs, scripts, or applications. Extends ts-coder, inherits its Node.js, pnpm, typing, and documentation rules, and overrides its basic testing guidance for test strategy, structure, mocking, fixtures, coverage, async tests, and test data. Framework skills may further override test environment and placement.
---

# TypeScript QA Engineer

## Inheritance and Precedence

Apply the most specific applicable rule. The rows are ordered from narrowest to
broadest ownership.

| Domain | Governing skill |
|---|---|
| Test environment, file placement, and framework integration | Applicable framework skill |
| Test strategy, structure, mocking, fixtures, coverage, async tests, and test data | **ts-qa-engineer** |
| Node.js, pnpm, typing, documentation, and general coding rules | **ts-coder** |

## Quick Reference

| Task | Command |
|---|---|
| Run all tests | `pnpm exec vitest run` |
| Run unit tests only | `pnpm exec vitest run tests/unit` |
| Run integration tests | `pnpm exec vitest run tests/integration` |
| Run e2e tests | `pnpm exec vitest run tests/e2e` |
| Run a specific file | `pnpm exec vitest run <path>` |
| Run with watch mode | `pnpm exec vitest` |
| Stop on first failure | `pnpm exec vitest run --bail=1` |
| Run matching pattern | `pnpm exec vitest run -t "pattern"` |

## Three-Tier Testing Strategy

For framework-agnostic projects, tiers are directory-based — select them with
`pnpm exec vitest run tests/<tier>`. A framework skill may override where its
unit/component tests live while preserving the three-tier strategy.

### Test Directory Layout

```text
tests/
├── unit/              # Fully isolated, all externals mocked
├── integration/       # Tests interaction between components and/or real services
├── e2e/               # Full workflow through the application's public interface
└── helpers/           # Shared factory functions, test utilities, custom matchers
```

Mirror the source tree inside each tier directory. For `src/services/user.ts`,
place unit tests at `tests/unit/services/user.test.ts`.

### Unit Tests

Replace external effects such as databases, filesystems, networks, queues, and
clocks with test doubles or fakes so unit tests run without infrastructure.

```typescript
import { describe, expect, it, vi } from "vitest";
import { UserService } from "../../../src/services/user";

describe("UserService.getUser", () => {
  it("returns user when found", async () => {
    const repo = {
      getById: vi.fn((id: string) => Promise.resolve({ id, name: "Alice" })),
    };
    const service = new UserService(repo);

    const result = await service.getUser("1");

    expect(result).toEqual({ id: "1", name: "Alice" });
    expect(repo.getById).toHaveBeenCalledWith("1");
  });

  it("returns null when not found", async () => {
    const repo = {
      getById: vi.fn(() => Promise.resolve(null)),
    };
    const service = new UserService(repo);

    const result = await service.getUser("999");

    expect(result).toBeNull();
  });
});
```

Rules:
- Mock at the boundary (ports, adapters, I/O interfaces), not internal functions.
- Assert observable outputs or state. Assert dependency calls only when the
  interaction itself is part of the contract.
- Use `vi.fn()` for standalone functions and `vi.spyOn()` for methods on existing objects.

### Integration Tests

Test interaction between multiple components. Mock external services when the
test goal is to verify data flow and contracts between your own components. Use
real services only when the test goal is to verify the I/O layer itself, such as
SQL query syntax or cache TTL behavior. When in doubt, default to mocking.

For concrete boundary-crossing tests, load
**[Integration and End-to-End Examples](references/integration-and-e2e.md)**.
It covers a database-backed integration and a CLI workflow with temporary
filesystem isolation.

### End-to-End Tests

Exercise a full workflow through the application's **public interface** — the
same interface a user or consumer would invoke:

| Application type | Public interface | E2E approach |
|---|---|---|
| CLI tool | Shell commands | Node.js `child_process` APIs |
| Library/package | Public module API | Import and call public exports directly |
| HTTP API | HTTP endpoints | `fetch()` against a running server |
| Script | Script entrypoint | `execFile("pnpm", ["run", "<script>", "--", ...])` |

Rules:
- No internal imports in e2e tests — interact only through the public interface.
- Test the full happy path and critical failure modes.
- Use temporary directories for filesystem isolation.

## Test Structure & Organization

Use `describe` blocks to group tests by the single functionality each block covers:

```typescript
describe("parseConfig", () => {
  it("returns defaults when file is missing", () => { /* ... */ });
  it("parses valid TOML", () => { /* ... */ });
  it("throws on malformed TOML", () => { /* ... */ });
  it("ignores unknown keys", () => { /* ... */ });
});
```

Rules:

1. **One `describe` per functionality** — never mix unrelated behaviors.
2. **One assertion focus per `it`** — test a single expected case, known failure
  mode, or edge case.
3. **Cover the applicable behavior categories for the functionality:**
   - Happy path — expected inputs produce correct output.
   - Failure modes — bad input, missing resources, permission errors, thrown exceptions.
   - Edge cases — empty collections, boundary values, `null`, `undefined`, Unicode, very large inputs.
4. **Descriptive test names** — `it("<behavior> when <condition>")`. The name
  must convey what is being tested without reading the body.
5. **No shared mutable state** between tests. Each test must be fully independent.

## Mocking & Test Doubles

### Vitest Mocking API

| Double | Use when |
|---|---|
| `vi.fn(fn)` | Creating a tracked callable with custom implementation |
| `vi.spyOn(obj, "method")` | Observing or replacing a method on an existing object |
| `vi.mock("mod", () => ...)` | Replacing an entire module import |
| Manual stub object | Implementing a port/interface for testing |

### Module Mocking

```typescript
import { vi } from "vitest";

vi.mock("../../../src/adapters/http-client", () => ({
  fetchData: vi.fn(() => Promise.resolve({ status: 200, data: [] })),
}));
```

### Spy Example

```typescript
import { expect, vi } from "vitest";

const logger = { info: (...args: unknown[]) => { void args; } };
const spy = vi.spyOn(logger, "info");

doSomething(logger);

expect(spy).toHaveBeenCalledWith("operation complete");
```

### Patching Guidelines

- Mock the module specifier imported by the subject under test. Remember that
  `vi.mock` is hoisted; use `vi.doMock` for non-hoisted, subsequent imports.
- Scope mocks as narrowly as possible — prefer per-test over suite-wide.
- Assert call counts or arguments when the interaction is behaviorally
  significant, not merely because a mock exists.

## Fixtures & Test Helpers

### Lifecycle Hooks

| Hook | Scope | Use for |
|---|---|---|
| `beforeEach` / `afterEach` | Per test | Most setup/teardown — ensures isolation |
| `beforeAll` / `afterAll` | Per `describe` | Expensive shared resources (DB pools, containers) |

Rules:
- Default to `beforeEach`/`afterEach`. Use `beforeAll`/`afterAll` only for genuinely expensive resources.
- Resources shared via `beforeAll` must be **read-only** or reset between tests.
- Always clean up in the corresponding `after*` hook.

### Factory Functions

Place shared test utilities in `tests/helpers/`. Use factory functions to create
test data — avoid hardcoding objects across multiple tests:

```typescript
// tests/helpers/factories.ts
export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: "1",
    name: "Alice",
    email: "alice@test.com",
    ...overrides,
  };
}
```

```typescript
import { makeUser } from "../helpers/factories";

describe("validateUser", () => {
  it("rejects empty name", () => {
    const user = makeUser({ name: "" });

    expect(() => validateUser(user)).toThrow();
  });
});
```

## Edge Cases & Coverage Patterns

Select cases from this checklist according to the input domain, failure risk,
and behavior owned by the subject under test:

| Category | Examples |
|---|---|
| Empty inputs | `[]`, `{}`, `""`, `null`, `undefined`, `0` |
| Boundary values | Off-by-one, `Number.MAX_SAFE_INTEGER`, min/max length, first/last element |
| Type boundaries | `null`/`undefined` where a value is expected, wrong type if untyped |
| Unicode & encoding | Emoji, multibyte chars, mixed encodings, RTL text |
| Large inputs | Arrays with 10k+ items, deeply nested objects, long strings |
| Error propagation | Thrown errors from dependencies, timeouts, partial failures |
| Concurrency | Simultaneous calls, race conditions (when applicable) |
| Idempotency | Calling the same operation twice produces the same result |

## Parameterized Tests

Use `it.each` when testing the same logic with multiple inputs:

```typescript
describe("slugify", () => {
  it.each([
    ["Hello World", "hello-world"],
    ["  spaces  ", "spaces"],
    ["UPPER", "upper"],
    ["special!@#chars", "specialchars"],
    ["", ""],
    ["already-slug", "already-slug"],
  ])('converts "%s" to "%s"', (input, expected) => {
    expect(slugify(input)).toBe(expected);
  });
});
```

Rules:
- Use `it.each` for **data variation**, not for testing different behaviors.
  Different behaviors get separate `it` blocks.
- Include relevant edge cases in the parameter list, such as an empty string,
  `null`, or a boundary value when the input contract permits them.

## Async Testing

Async test functions are natively supported — return a `Promise` or use `async`/`await`:

```typescript
describe("asyncFetch", () => {
  it("returns data on success", async () => {
    const client = {
      get: vi.fn(() => Promise.resolve({ status: 200, data: [1, 2, 3] })),
    };

    const result = await asyncFetch(client, "/items");

    expect(result).toEqual([1, 2, 3]);
  });

  it("throws on network failure", async () => {
    const client = {
      get: vi.fn(() => Promise.reject(new Error("timeout"))),
    };

    await expect(asyncFetch(client, "/items")).rejects.toThrow("timeout");
  });
});
```

Always `await` `.rejects` and `.resolves` assertions; omitting `await` causes the assertion to be silently skipped.

## Test Data Management

Rules:
- Use **factory functions** in `tests/helpers/` to create test data; avoid
  hardcoding objects across multiple tests.
- Keep test data minimal — include only fields relevant to the test.
- Use `fs.mkdtempSync(path.join(os.tmpdir(), "test-"))` or
  `fs.promises.mkdtemp()` for file-based test data; never write to the project
  directory.
- For database tests, create data in `beforeEach` and clean up via transaction rollback or truncation.

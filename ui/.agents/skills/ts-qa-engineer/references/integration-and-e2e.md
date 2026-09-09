# Integration and End-to-End Examples

Load this reference when implementing tests that cross component boundaries,
use real infrastructure, invoke a CLI, or exercise another public interface.
Keep the strategy and isolation rules from `ts-qa-engineer/SKILL.md` in force.

## Integration Test

Use real infrastructure only when the integration point itself is under test.
Reset or close shared resources in the matching lifecycle hook.

```typescript
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { PgUserRepository } from "../../../src/adapters/pg-user-repository";
import { UserService } from "../../../src/services/user";

describe("UserService + PgUserRepository", () => {
  let database: DatabaseConnection;
  let service: UserService;

  beforeAll(async () => {
    database = await createTestConnection();
    service = new UserService(new PgUserRepository(database));
  });

  afterAll(async () => {
    await database.close();
  });

  it("creates and retrieves a user", async () => {
    const created = await service.createUser({
      name: "Alice",
      email: "alice@test.com",
    });

    await expect(service.getUser(created.id)).resolves.toEqual(created);
  });
});
```

## CLI End-to-End Test

Invoke the configured package script through pnpm, assert observable output and
exit behavior, and isolate filesystem state in a temporary directory.

```typescript
import { execFile } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

const execFileAsync = promisify(execFile);

describe("CLI export command", () => {
  let testDirectory: string;

  beforeEach(async () => {
    testDirectory = await mkdtemp(join(tmpdir(), "cli-export-"));
  });

  afterEach(async () => {
    await rm(testDirectory, { force: true, recursive: true });
  });

  it("exports CSV to stdout", async () => {
    const inputFile = join(testDirectory, "input.json");
    await writeFile(inputFile, JSON.stringify([{ name: "Alice" }]));

    const { stdout } = await execFileAsync("pnpm", [
      "run", "cli", "--", "export", inputFile, "--format", "csv",
    ]);

    expect(stdout).toContain("Alice");
  });
});
```

Add separate tests for critical failure modes, including non-zero exit codes,
invalid input, unavailable dependencies, and cleanup after partial failure.

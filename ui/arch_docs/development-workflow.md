# Development Workflow

Build changes as coherent vertical outcomes rather than directory-shaped phases.

## Significant Work

Authentication, persistence, public contracts, major features, migrations, deployment,
and security boundaries use this sequence:

1. Approve a focused product contract with goals, non-goals, behavior, and success
   criteria.
2. Approve an owning technical design with routes, feature ownership, server/browser
   boundaries, persistence or provider responsibilities, tests, and acceptance.
3. Write focused failing tests where they clarify expected behavior.
4. Implement the smallest working vertical slice from route through feature and server
   boundary.
5. Add adapter-specific evidence and browser acceptance appropriate to the risk.
6. Update documentation and acceptance status with the implementation.

Review checkpoints do not automatically become document phases. Create numbered phases
only for true predecessor relationships, separately verifiable outcomes, material risk,
or distinct handoffs.

## Routine Work

Bug fixes, dependency maintenance, copy changes, and isolated refactors may use normal
issue and pull-request review when they preserve current product and architecture
contracts. Add tests that reproduce or protect the changed behavior.

## Verification

```sh
bun run verify
bun scripts/ui-visual-check.mjs
```

Run the visual check with `vite preview` serving the built shell and the OCR
server reachable. There is no container build: the desktop app ships as a
Tauri bundle (`bunx tauri build`).

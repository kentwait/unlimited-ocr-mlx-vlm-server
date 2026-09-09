# Source-Sensitive Edge Cases

Load this reference only when installed plugin behavior, generated behavior, or
an import-protection failure remains ambiguous after applying the domain
references.

Source basis: public `@tanstack/react-start` exports, client/server runtime
behavior, plugin option schemas, maintained examples, and Start test fixtures.

## Plugin Options to Verify

Inspect the installed plugin schema before changing high-impact options such as
`srcDirectory`, router/client/server entries and bases, `serverFns.base`,
`serverFns.generateFunctionId`, `pages`, `sitemap`, `prerender`, `spa`, or
`importProtection`.

Fix import-boundary violations before weakening protection. If customization is
required, verify client/server file patterns, include/exclude rules, behavior,
mock access, violation handling, logging, and trace depth against the installed
version.

## Troubleshooting

- `405` from a server function: compare the declared and caller/form methods.
- Large GET input or GET with `FormData`: use POST.
- Server helper in a client bundle: move it behind `*.server.ts` and call it
  through a server function or server route.
- Import-protection violation: inspect the import graph before changing policy.
- Stale loader-backed UI after mutation: call `router.invalidate()`.
- Private UI with exposed data: authorize inside every private server function
  or server route, not only in `beforeLoad`.

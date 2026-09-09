# OCR Library UI

Tauri 2 desktop app for browsing OCR'd paper libraries. Three panes: library
tree (left), PDF preview (middle), markdown (right). Selecting a PDF loads its
`<stem>.md` + `<stem>.spans.jsonl` sidecars; the OCR button submits the PDF to
the unlimited-ocr server (`POST /parse/jobs`), polls progress, and saves the
sidecars next to the PDF.

## Prerequisites

- [bun](https://bun.sh) 1.x (installs, scripts, tests; `bun.lock` is the lockfile)
- Rust toolchain (`cargo`) for the Tauri shell
- The OCR server running (default `http://localhost:8300`)

Vite remains the bundler — TanStack Start builds on it. Bun replaces the Node
runtime and package manager, not the build tool.

## Develop

```sh
bun install
bun run dev        # vite on http://localhost:1421 (unique per app — the
                     # 1420 default collides when two Tauri apps run together)
bun run tauri:dev  # desktop window (runs dev server itself)
```

Point at a non-default server with `VITE_OCR_SERVER_URL`:

```sh
VITE_OCR_SERVER_URL=http://<lan-host>:8300 bun run tauri:dev
```

## Verify

```sh
bun run verify     # format → lint → typecheck → test → build
cargo check        # from src-tauri/, when Rust code changes
```

Browser acceptance (built shell + reachable OCR server, asserts zero console
errors):

```sh
bun run build
bunx vite preview --port 4173 --strictPort &
bun scripts/ui-visual-check.mjs
```

## Ship

```sh
bunx tauri build   # desktop bundle (frontendDist: dist/client, SPA mode)
```

## Layout

```text
src/
├── routes/            / route (library shell), thin route modules only
├── features/library/  the app: pages, components, schemas, Tauri + OCR clients
├── shared/components/ proven cross-feature UI primitives
├── lib/               focused utilities (cn, runtime detection)
├── router.tsx         fresh router factory
src-tauri/             Rust commands (root-scoped fs), Tauri config
ui/docs/dataflow/      planned lifecycle pairs (plan-data-flow contracts)
```

`routes -> features -> shared/lib`; the Rust command layer is the filesystem
boundary. See [`AGENTS.md`](AGENTS.md) for the binding contract.

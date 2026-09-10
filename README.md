# paperhub-parser (formerly unlimited-ocr-server)

> **Digital-born PDFs only.** This server converts PDFs into structured span
> JSONL using [pymupdf4llm](https://github.com/pymupdf/pymupdf4llm) (text,
> headings, reading order — from the PDF's own text layer) and
> **PP-DocLayout-S** (figure regions, cropped inline). There is **no OCR and
> no LLM**: text is exact by construction, and pages without a text layer
> (scans) are rejected with a 400 until scan routing lands.

The companion desktop app (Paperhub) consumes this server as a pinned git
submodule over the `spans_jsonl` contract: one JSON record per span with
`id`, `page`, `label`, `box` (0-1000), `text`, and an optional inline PNG
`image` for figure spans.

## Requirements

- Python 3.10+ (any OS — CPU only, no GPU, no Apple Silicon requirement)
- No model downloads: the 4.7 MB PP-DocLayout-S ONNX export is vendored
  under `src/ocr_server/models/` (see `MODEL_INFO.md` for source, SHA256,
  license, and preprocessing).

## Setup

```bash
uv sync --group dev
```

## Run

```bash
uv run ocr-server                        # http://localhost:8300
uv run ocr-server --host 0.0.0.0         # LAN-accessible
uv run ocr-server --port 8301
uv run ocr-server --layout-model /path/to/pp_doclayout_s.onnx   # override
```

`GET /health` reports readiness, the parser, and the loaded layout model.

## API

`POST /parse/pdf` — multipart:
- `file`: PDF (digital-born; text layer required)
- `pages`: `"all"` | `"1-3,5"` (default all; max 50 pages/request)
- `dpi`: render resolution for figure crops, 72–300 (default 150)

Returns `{kind, n_pages, results: [{page, elapsed_s, spans_jsonl, warnings}],
total_elapsed_s}`.

`POST /parse/jobs` + `GET /parse/jobs/{job_id}` — same form fields, async
(202 + `job_id`; poll until `done`/`error`). Use for long documents.

### Span contract (`spans_jsonl`)

One JSON object per line:

```json
{"id": "p1-1", "page": 1, "label": "title", "box": [64, 56, 945, 131], "text": "..."}
{"id": "p1-14", "page": 1, "label": "image", "box": [63, 605, 637, 875], "text": "",
 "image": "data:image/png;base64,..."}
```

- `id`: `p{page}-{index}`, assigned in reading order — the identity contract
  the app renders and highlights by.
- `box`: `[x1, y1, x2, y2]` normalized 0–1000.
- `label`: `text`, `title`, `list-item`, `caption`, `footnote`, `header`,
  `footer`, `page_number`, `image`, `figure_text` (content inside a figure
  region; kept for losslessness, dropped by renderers).
- `image`: figure pixels as an inline PNG data URI; `page` + `box` stay on
  the span so a consumer can reconstitute the crop from the source PDF.

### Pipeline

1. Text-layer check per requested page; any page without text → 400.
2. pymupdf4llm Layout over PDF internals (labels + reading order).
3. One render per page; PP-DocLayout-S detects figure regions (`image`,
   `chart`), which must corroborate a native picture box (IoU ≥ 0.4) to
   become figure spans; crops are inlined.
4. Merge: picture boxes replaced by figure spans at their reading position,
   content inside figures relabeled `figure_text`, ids assigned.

## Assistant (optional)

The server can also host the local chat model Paperhub uses. This is optional
and Apple-Silicon-only; parsing works without it.

```bash
uv sync --extra assistant                                        # mlx-vlm + huggingface-hub
HF_TOKEN=hf_... uv run ocr-server                                # optional Hub auth
uv run ocr-server                                                # hosts /assistant/* and /v1/chat/completions
OCR_ASSISTANT_FAKE=1 uv run ocr-server                           # deterministic fake (CI, UI dev)
uv run ocr-server --assistant-model mlx-community/Qwen3.5-9B-MLX-4bit
```

Models come from a data-driven catalog of pinned Qwen3.5-9B MLX
quantizations (`mlx-community/Qwen3.5-9B-MLX-8bit` default,
`mlx-community/Qwen3.5-9B-MLX-4bit`). Each entry tracks its own cache state;
one is loaded at a time.

- `GET /assistant/status` — `{available, state, model, loaded, progress,
  detail, models}` with state `not_downloaded | downloading | paused |
  loading | ready | failed`; `models` carries per-entry
  `{id, label, bits, size_bytes, downloaded, partial, active}`. `downloaded`
  means a *complete* snapshot (`snapshot_download(local_files_only=True)`
  succeeds); a cancelled/in-progress cache reports `partial: true` so clients
  offer Resume rather than Use.
- `GET /assistant/models` — the catalog and per-entry state.
- `POST /assistant/model/download {model?}` — explicit, idempotent,
  resumable download (Hugging Face cache), then load. Defaults to the
  selected model.
- `POST /assistant/model/use {model}` — switch the resident model (unloads
  the previous weights first).
- `POST /assistant/model/cancel` — abort an in-flight download; the entry
  becomes `paused` with partial files kept for resume.
- `POST /v1/chat/completions` — OpenAI-compatible subset (`messages`,
  `tools`, `stream`). Streaming replies are SSE `data:` chunks; Qwen XML
  tool calls are parsed into OpenAI `tool_calls` deltas; `<think>` content
  is stripped. Without the extra (or an unloaded model) the endpoints return
  501/409 so the app can explain the state.

`snapshot_download` internals: cancellation is delivered through a
`tqdm_class` that raises when the cancel event is set; complete files are
skipped on the next call, so resume continues from the partial cache.

## Testing

```bash
make test        # pytest (deterministic; runs on any platform)
make coverage    # fail_under=95 (currently 100%)
make mutate      # manual mutation run (mutmut), never CI
```

## License

Apache-2.0 (see `LICENSE`). PyMuPDF/pymupdf4llm are AGPL-3.0 (dual
licensed); the vendored PP-DocLayout-S ONNX export derives from
Apache-2.0 weights.

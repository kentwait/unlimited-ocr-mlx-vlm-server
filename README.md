# unlimited-ocr-server

> **Desktop app moved out.** The Tauri companion app (formerly `ui/` in this
> repo) now lives in the Paperhub repo (history preserved via renames), which
> consumes this server as a pinned git submodule over the `spans_jsonl` +
> sidecar contract. This repo stays server-only: generic PDF → markdown
> (OCR + support LLM + generic repetition-based furniture removal).
> Journal-specific templates moved to Paperhub's reflow layer, so the
> `furniture` form field now accepts only `auto` (generic fingerprinting)
> or `none` (disabled); anything else is a 400.

LAN-accessible FastAPI server wrapping **baidu/Unlimited-OCR** (DeepSeek-OCR
lineage) as quantized by [sahilchachra/unlimited-ocr-mxfp8-mlx](https://huggingface.co/sahilchachra/unlimited-ocr-mxfp8-mlx)
(block-float MXFP8, ~3.7 GB on disk, ~5 GB peak memory). Serves
**PDF → markdown** (per-page) and **image → markdown** over multipart HTTP.
Runs the model through [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) on Apple
Silicon.

No vendored model code — the server depends on the `mlx-vlm` package, which
natively supports this architecture (`model_type: "deepseekocr"`, config
already patched upstream).

## Setup

```bash
uv sync                                # deps (Py3.10+, Apple Silicon)
uv run python scripts/download_model.py   # optional; first server start downloads anyway
```

## Run

```bash
uv run ocr-server                        # http://localhost:8300, model loads on startup
uv run ocr-server --host 0.0.0.0         # LAN-accessible: other machines use http://<this-mac-ip>:8300
uv run ocr-server --port 8301 --model-ref /path/to/local/model
uv run ocr-server --fake-engine          # no model; stub responses for client dev
uv run pytest                            # API tests run against the fake engine
```

First start with the real model: downloads (~3.7 GB) + weight load; allow a few
minutes. `GET /health` shows readiness.

## Configuration

### Server defaults (CLI flags / env vars)

```bash
uv run ocr-server --host 0.0.0.0 --port 8300 \
                  --model-ref sahilchachra/unlimited-ocr-mxfp8-mlx
```

| what | CLI flag | env var | default |
|---|---|---|---|
| Bind address | `--host` | `OCR_HOST` | `127.0.0.1` (set `0.0.0.0` for LAN access) |
| Port | `--port` | `OCR_PORT` | `8300` |
| OCR model | `--model-ref` | `OCR_MODEL_REF` | `sahilchachra/unlimited-ocr-mxfp8-mlx` |
| Support stage | — | `OCR_SUPPORT` | `1` (set `0` to disable; `OCR_CLEANUP` still honored as fallback) |
| Support model | — | `OCR_SUPPORT_MODEL` | `mlx-community/Qwen3.5-0.8B-MLX-8bit` (`OCR_CLEANUP_MODEL` still honored as fallback) |
| Prompts directory | — | `OCR_PROMPTS_DIR` | `./prompts` (loaded at startup; restart to apply edits) |
| Stub engine (dev) | `--fake-engine` | `OCR_FAKE_ENGINE=1` | off |

`--model-ref` / `OCR_MODEL_REF` accept any HF repo id or local directory
containing an mlx-vlm model. The support model only loads on first use, so
`OCR_SUPPORT=0` also saves its memory entirely.

### Per-request (multipart form fields)

All fields below are optional and override the defaults above per call — see
the API section for the full list. The two that matter most for quality/speed
on publisher PDFs:

- **`dpi`** — default **300**. Recall plateaus 150–300, but 300 is the only
  loop-free zone for the mxfp8 OCR model on dense pages; 72 is never worth it.
  Full DPI × quant table: [MODEL_COMPARISON.md](MODEL_COMPARISON.md).
- **`ocr_model`** — `default` (server default model), `bf16`
  (`mlx-community/Unlimited-OCR-bf16`: loop-free at every DPI, ~40% slower,
  +3 GB), or any HF repo id / local path. Alternates load lazily on first use
  and stay resident, so you can mix per batch. Rule of thumb: default for
  everything, `bf16` for a page that came back `early_stop=true`.

### Benchmark scripts (`scripts/compare_*.py`)

Each script has a **USER CONFIG** block at the top with inline `<-- CHANGE`
markers:

| variable | meaning | env override (compare_ocr only) |
|---|---|---|
| `PDF_PATH` | test PDF with an embedded text layer | `OCR_CMP_PDF` |
| `PAGE_NUMBERS` | pages to test (1-indexed) | `OCR_CMP_PAGES` |
| `DPIS` | render resolutions to sweep | `OCR_CMP_DPIS` |
| `WORK_DIR` | scratch dir for images/results | `OCR_CMP_WORKDIR` |

Typical sweep (no file edits needed):

```bash
export OCR_CMP_PDF=/path/to/paper.pdf OCR_CMP_PAGES=1,2 OCR_CMP_DPIS=72,150,300
uv run python scripts/compare_ocr.py sahilchachra/unlimited-ocr-mxfp8-mlx mxfp8
uv run python scripts/compare_ocr.py mlx-community/Unlimited-OCR-bf16 bf16
uv run python scripts/compare_cleanup.py mlx-community/Qwen3.5-0.8B-MLX-8bit q8
```

Run `compare_ocr.py` first — it renders pages and caches raw OCR text that
`compare_cleanup.py` reuses. Metrics land in `WORK_DIR/ocr-cmp-<tag>.json` and
`cleanup-cmp-<tag>.json`.

### Prompts (`prompts/*.md`)

The support LLM's prompts are **Markdown + Jinja2 templates** in `prompts/`,
loaded once at server startup — edit and restart to change.

| file | used for | variables |
|---|---|---|
| `prompts/support_digital.md` | pages with a text layer | `{{ fragments }}`, `{{ text_layer }}`, `{{ page }}` |
| `prompts/support_scan.md` | scanned pages (no text layer) | `{{ fragments }}`, `{{ page }}` |
| `prompts/layout_scan.md` | layout pre-scan (vision, low-res thumbnail) | `{{ page }}` |

Rules: templates are passed to the model verbatim (write them as Markdown —
headers/fences are fine); every variable is required (`StrictUndefined` — a
misspelled or missing variable is a **startup error**, not an empty string in
a prompt); each template is dry-rendered at boot, so Jinja syntax errors fail
the server start with a pointed message. Point `OCR_PROMPTS_DIR` at a
different directory to experiment with prompt variants without touching the
repo's.

## API

`GET /health` → engine status, model ref, device.

`POST /parse/image` — multipart:
- `file`: JPEG/PNG/WebP
- optional: `prompt` (default `document parsing.`), `max_tokens` (default 8192),
  `temperature` (0.0), `base_size` (1024), `image_size` (640),
  `cropping` (default true = gundam mode), `ocr_model` (`default` | `bf16` |
  any HF repo id or local path — alternates lazy-load once and stay resident)

`POST /parse/pdf` — multipart:
- `file`: PDF
- `pages`: `"all"` | `"1-3,5"` (default all; max 50 pages/request)
- `dpi`: render resolution, 72–300 (default 300; avoid 72 — it degrades
  recall and triggers repetition loops on dense pages, see `MODEL_COMPARISON.md`)
- optional OCR params as above (`cropping` defaults **true** — gundam mode;
  dense two-column publisher pages degenerate in base mode, which is only
  faster for sparse single-column pages), plus `ocr_model` — use `bf16` for
  loop-sensitive dense batches (see `MODEL_COMPARISON.md`)

Both return `{kind, n_pages, results: [{page, markdown, elapsed_s, tokens, tps,
peak_memory_gb, early_stop, support_method, support_elapsed_s, support_early_stop,
`layout` (pre-scan profile),
corrections, spans_jsonl}], total_elapsed_s}`.

- **`spans_jsonl`** — the structured OCR intermediate: one JSON record per
  detected span, `{"page", "label" (title/text/image/…), "box" ([x1,y1,x2,y2]
  in the model's 0–1000 space), "text"}`. Markdown is rendered deterministically
  from these spans; consume the JSONL directly if you want boxes/labels.
- **`corrections`** — what the support model changed, content vs formatting:
  `{text_layer_backed, ocr_vocab_backed, invented, formatting_only,
  format_added_words, format_removed_words, samples_invented,
  samples_text_layer_backed}`. Content edits are word-level changes; `invented`
  = words with no source in the text layer or OCR output (model intuition —
  audit these). Formatting is markdown-transform churn, counted but not
  attributed.

### Layout pre-scan + support stage (default on)

Every page first gets a cheap vision pre-scan by the support model on a downscaled thumbnail: column count, running header/footer text, and large figure boxes. The profile is used twice — as a one-sentence hint appended to the OCR prompt ("two-column, big figure bottom-right — read columns top-to-bottom, skip it") and as a deterministic span filter (figure-interior and furniture text relabeled, never renumbered). Any scan failure falls back to the unhinted pipeline. Gundam tiling stays always on.

All pages then get the support LLM. Digital pages: reconcile with the text layer
(ground truth for wording/numbers) + proofread. Scanned pages (no text layer):
proofread-only prompt — fix obvious OCR misspellings from context, never
paraphrase; every edit is attributed in `corrections` and logged at INFO
(`OCR_LOG_LEVEL` env var controls the level), so hallucination risk stays
visible. Strips `<|det|>` markers, fixes loop remnants, emits clean Markdown
(~5-20 s/page extra).

Disable with `OCR_SUPPORT=0`; swap the model with `OCR_SUPPORT_MODEL=<hf-repo>`.

`POST /parse/jobs` + `GET /parse/jobs/{job_id}` — same as `/parse/pdf` but async
(202 + `job_id`; poll until `done`/`error`). Use for long documents.

### curl

```bash
curl -s http://localhost:8300/health

curl -s -F file=@scan.pdf -F pages=1-3,5 \
  http://localhost:8300/parse/pdf | jq -r '.results[].markdown' > out.md

curl -s -F file=@photo.jpg http://localhost:8300/parse/image | jq -r '.results[0].markdown'

# From another machine on the LAN (requires --host 0.0.0.0 and the firewall
# allowlist below): replace localhost with this Mac's IP, e.g. http://192.168.1.20:8300
```

### Python

```python
import requests
r = requests.post("http://localhost:8300/parse/pdf",
                  files={"file": open("scan.pdf", "rb")},
                  data={"pages": "all"})
for page in r.json()["results"]:
    print(page["page"], page["markdown"])
```

## Prompts (DeepSeek-OCR vocabulary)

| Task | Prompt |
|---|---|
| Document → Markdown (native parse) | `document parsing.` *(default)* |
| Plain text OCR, no layout | `Free OCR.` |
| OCR + bounding boxes | `<|grounding|>Convert the document to markdown.` |
| Parse a figure/chart | `Parse the figure.` |

With `<|grounding|>` the output interleaves `<|det|>...[x1,y1,x2,y2]<|/det|>`
boxes; strip them client-side if you only want text.

Model selection rationale and per-variant benchmarks (mxfp8 / int8 / bf16,
Qwen3.5 0.8B / 2B × 4-bit / 8-bit / bf16): see [MODEL_COMPARISON.md](MODEL_COMPARISON.md).

## LAN access (macOS firewall)

The server binds to `localhost` by default. To serve other machines on your
LAN, start it with `--host 0.0.0.0` — clients then use
`http://<this-mac-ip>:8300`. Additionally, the uv-managed CPython binary is
ad-hoc signed and the macOS Application Firewall the macOS Application Firewall
**silently drops** inbound connections to it from other hosts (loopback still
works, so `127.0.0.1` tests pass while LAN clients time out). Allow it once:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add .venv/bin/python
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp .venv/bin/python
```

(The symlink resolves to the shared uv CPython, so one allowlist entry covers
every uv project using that interpreter.)

## Design notes

- **PDF pipeline**: PyMuPDF renders each requested page to PNG at `dpi`
  (default 300 — the loop-free zone for quantized OCR models on dense pages),
  then one `generate()` call per page image. Page results keep their 1-indexed
  page number.
- **Serialization**: model access funnels through `anyio.CapacityLimiter(1)` —
  concurrent requests queue instead of fighting over unified memory. The
  blocking MLX call runs in a worker thread so the event loop stays responsive.
- **Resolution modes**: gundam (`cropping=true`, 1024 global + 640 tiles) for
  both single images and rendered PDF pages by default — dense academic pages
  hallucinate in base mode (273-token global view too coarse). Base mode
  (`cropping=false`) is the fast path for sparse single-column pages.
- **Degenerate-loop handling**: token-tail near-periodicity check (no GPU sync)
  breaks repetition loops early; loop tail trimmed, duplicate long lines
  deduped, `early_stop=true` flagged in the page result.
- ` mlx-vlm` requires the literal `<image>` token in the prompt; the server
  inserts it via `apply_chat_template` (num_images=1) before calling `generate`.

## License

Apache-2.0 (see `LICENSE`). Model weights keep their own licenses —
Unlimited-OCR: MIT (Baidu); Qwen3.5: Apache-2.0.

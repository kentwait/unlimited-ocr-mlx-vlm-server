# unlimited-ocr-server

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
uv run ocr-server                       # 0.0.0.0:8300, model loads on startup
uv run ocr-server --port 8301 --model-ref /path/to/local/model
uv run ocr-server --fake-engine         # no model; stub responses for client dev
uv run pytest                           # API tests run against the fake engine
```

First start with the real model: downloads (~3.7 GB) + weight load; allow a few
minutes. `GET /health` shows readiness.

## API

`GET /health` → engine status, model ref, device.

`POST /parse/image` — multipart:
- `file`: JPEG/PNG/WebP
- optional: `prompt` (default `document parsing.`), `max_tokens` (default 8192),
  `temperature` (0.0), `base_size` (1024), `image_size` (640),
  `cropping` (default true = gundam mode)

`POST /parse/pdf` — multipart:
- `file`: PDF
- `pages`: `"all"` | `"1-3,5"` (default all; max 50 pages/request)
- `dpi`: render resolution, 72–300 (default 150)
- optional OCR params as above (`cropping` defaults **true** — gundam mode;
  dense two-column publisher pages degenerate in base mode, which is only
  faster for sparse single-column pages)

Both return `{kind, n_pages, results: [{page, markdown, elapsed_s, tokens, tps,
peak_memory_gb, early_stop, cleanup_method, cleanup_elapsed_s, cleanup_early_stop}],
total_elapsed_s}`.

### Cleanup stage (default on)

For PDF pages with an embedded text layer (digital-born publisher PDFs), a small
LLM (`mlx-community/Qwen3.5-0.8B-MLX-4bit`, ~1 GB, loaded lazily on first use)
reconciles the OCR markdown with the publisher text layer: text layer is ground
truth for wording/numbers, OCR supplies structure. Strips `<|det|>` markers,
fixes loop remnants, emits clean Markdown (~5-20 s/page extra). Scanned pages
(no text layer) and all `/parse/image` uploads get a deterministic pre-clean
only (markers stripped, no LLM — no hallucination risk on pure-OCR input).

Disable with `OCR_CLEANUP=0`; swap the model with `OCR_CLEANUP_MODEL=<hf-repo>`.

`POST /parse/jobs` + `GET /parse/jobs/{job_id}` — same as `/parse/pdf` but async
(202 + `job_id`; poll until `done`/`error`). Use for long documents.

### curl

```bash
curl -s http://mac.local:8300/health

curl -s -F file=@scan.pdf -F pages=1-3,5 -F dpi=200 \
  http://mac.local:8300/parse/pdf | jq -r '.results[].markdown' > out.md

curl -s -F file=@photo.jpg http://mac.local:8300/parse/image | jq -r '.results[0].markdown'
```

### Python

```python
import requests
r = requests.post("http://mac.local:8300/parse/pdf",
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

## LAN access note (macOS firewall)

The uv-managed CPython binary is ad-hoc signed; the macOS Application Firewall
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
  (150 ≈ good A4 default; 200–300 for small print), then one `generate()` call
  per page image. Page results keep their 1-indexed page number.
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

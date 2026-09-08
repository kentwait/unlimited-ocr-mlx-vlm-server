# unlimited-ocr-server

LAN-accessible FastAPI server that wraps [LoJexLLM/Unlimited-OCR-MLX](https://huggingface.co/LoJexLLM/Unlimited-OCR-MLX)
(MLX port of Baidu's Unlimited-OCR, DeepSeek-OCR lineage) and serves
**PDF → markdown** (per-page) and **image → markdown** over multipart HTTP.
Apple Silicon only (MLX).

The upstream repo is vendored as a git **submodule** (`vendor/Unlimited-OCR-MLX`).
Its 6.7 GB weights are *not* in the submodule (git-lfs) — download them separately
into `models/Unlimited-OCR-MLX/` (default, git-ignored).

## Setup

```bash
uv sync                      # creates .venv, resolves deps (Py3.10+, Apple Silicon)
git submodule update --init  # vendor code (if you cloned fresh)
uv run scripts/download_model.py    # ~6.7 GB -> models/Unlimited-OCR-MLX/
```

## Run

```bash
uv run ocr-server                     # 0.0.0.0:8300, model on startup (first load is slow)
uv run ocr-server --port 8301 --model-dir /path/to/Unlimited-OCR-MLX
uv run ocr-server --fake-engine       # no model; stub responses for client dev
uv run pytest                         # API tests run against the fake engine
```

## API

`GET /health` → engine status, model dir, device.

`POST /parse/image` — multipart:
- `file`: JPEG/PNG/WebP
- optional: `prompt` (default `document parsing.`), `max_length`, `temperature`, `base_size`, `image_size`, `crop_mode` (default true = gundam/dynamic-tiling)

`POST /parse/pdf` — multipart:
- `file`: PDF
- `pages`: `"all"` | `"1-3,5"` (default all; max 50 pages/request)
- `dpi`: render resolution, 72–300 (default 150)
- optional OCR params as above, except `crop_mode` defaults **false** (base mode — upstream guidance for multi-page)

Both return `{kind, n_pages, results: [{page, markdown, elapsed_s, ...}], total_elapsed_s}`.

`POST /parse/jobs` + `GET /parse/jobs/{job_id}` — same as `/parse/pdf` but async
(202 + `job_id`; poll status until `done`/`error`). Useful for long documents.

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

- **Submodule**: `vendor/Unlimited-OCR-MLX` is a *flat* package (package files at
  repo root, dashes in the dir name) — `ocr_server.engine` registers it as the
  importable package `unlimited_ocr_mlx` via importlib.
- **PDF pipeline**: PyMuPDF renders each requested page to PNG at `dpi`
  (150 ≈ good default for A4; 200–300 for small print), then one
  `infer_single()` call per page image. Page results keep their 1-indexed page number.
- **Serialization**: model access is funneled through `anyio.CapacityLimiter(1)` —
  concurrent requests queue instead of corrupting GPU memory. The blocking MLX
  call runs in a worker thread so the event loop stays responsive.
- **Defaults follow upstream docs**: temperature 0, max_length 32768, gundam mode
  (`crop_mode=True, base_size=1024, image_size=640`) for single images, base mode
  (`crop_mode=False, image_size=1024`) for PDF pages.
- **Upstream quirks**: output text contains layout tags like `<|det|>...<|/det|>`
  and `<PAGE>` markers; strip downstream if you want pure markdown. The engine
  prints progress to stdout; server logs are separate.

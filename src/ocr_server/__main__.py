"""Entry point: `uv run ocr-server` / `python -m ocr_server`."""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def main() -> None:
    # Route ocr_server.* loggers (page/request summaries) to stderr at INFO so
    # they appear alongside uvicorn's request logs.
    logging.basicConfig(
        level=os.environ.get("OCR_LOG_LEVEL", "INFO").upper(),
        format="%(levelname)s:     %(name)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description="Paperhub PDF parser (FastAPI)")
    parser.add_argument("--host", default=os.environ.get("OCR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OCR_PORT", "8300")))
    parser.add_argument(
        "--layout-model",
        default=os.environ.get("OCR_LAYOUT_MODEL", ""),
        help="Path to a PP-DocLayout-S ONNX file (defaults to the vendored model)",
    )
    args = parser.parse_args()

    if args.layout_model:
        os.environ["OCR_LAYOUT_MODEL"] = args.layout_model

    uvicorn.run(
        "ocr_server.api:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover - script entry guard
    main()

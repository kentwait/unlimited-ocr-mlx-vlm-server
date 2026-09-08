"""Entry point: `uv run ocr-server` / `python -m ocr_server`."""

from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Unlimited-OCR MLX FastAPI server")
    parser.add_argument("--host", default=os.environ.get("OCR_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("OCR_PORT", "8300")))
    parser.add_argument(
        "--model-ref",
        default=os.environ.get("OCR_MODEL_REF", "sahilchachra/unlimited-ocr-mxfp8-mlx"),
        help="HF repo id or local path of the MLX model",
    )
    parser.add_argument(
        "--fake-engine",
        action="store_true",
        help="Use a stub engine (no model) for API development/testing",
    )
    args = parser.parse_args()

    os.environ["OCR_MODEL_REF"] = args.model_ref
    if args.fake_engine:
        os.environ["OCR_FAKE_ENGINE"] = "1"

    uvicorn.run(
        "ocr_server.api:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()

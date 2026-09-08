"""Optional: prefetch the model into the local HF cache (~3.7 GB).

The server loads by HF repo id by default and will download on first start;
this script just does it ahead of time.
"""

from __future__ import annotations

import argparse

from huggingface_hub import snapshot_download

DEFAULT_REPO = "sahilchachra/unlimited-ocr-mxfp8-mlx"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--local-dir", default=None, help="Also copy into this dir")
    args = parser.parse_args()

    print(f"Downloading {args.repo} (~3.7 GB) into the HF cache")
    snapshot_download(repo_id=args.repo, local_dir=args.local_dir)
    print("Done.")


if __name__ == "__main__":
    main()

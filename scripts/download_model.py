"""Download the MLX weights into models/Unlimited-OCR-MLX via huggingface_hub."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

REPO_ID = "LoJexLLM/Unlimited-OCR-MLX"
# Skip the git-lfs pointer noise; we only need the actual weight/config files.
IGNORE = ["*.md", ".gitattributes"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        default="models/Unlimited-OCR-MLX",
        help="Target directory (default: models/Unlimited-OCR-MLX)",
    )
    args = parser.parse_args()

    dest = Path(args.dest).expanduser().resolve()
    print(f"Downloading {REPO_ID} -> {dest} (~6.7 GB)")
    snapshot_download(
        repo_id=REPO_ID,
        local_dir=str(dest),
        ignore_patterns=IGNORE,
    )
    print("Done.")


if __name__ == "__main__":
    main()

"""Dev-only stub engine so the server can be exercised without the 6.7GB model."""

from __future__ import annotations

import time
from pathlib import Path


class FakeEngine:
    fake = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.loaded = False

    @property
    def model_dir(self):
        return None

    @property
    def vendor_dir(self):
        return None

    def load(self) -> None:
        self.loaded = True

    def infer_image_file(self, image_path: str, **params) -> str:
        self.calls.append((image_path, params))
        time.sleep(0.02)
        return f"MOCK({Path(image_path).name}|{params.get('prompt')})"

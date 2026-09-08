"""Dev-only stub engine so the server can be exercised without the model."""

from __future__ import annotations

import time
from pathlib import Path

from .engine import InferenceStats


class FakeEngine:
    fake = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.loaded = False
        self.model = "fake"
        self.processor = "fake"
        self.model_ref = None

    def load(self) -> None:
        self.loaded = True

    def infer_image_file(self, image_path: str, **params) -> tuple[str, InferenceStats]:
        self.calls.append((image_path, params))
        time.sleep(0.02)
        text = f"MOCK({Path(image_path).name}|{params.get('prompt')})"
        return text, InferenceStats(tokens=len(text), tps=100.0, peak_memory_gb=0.1)

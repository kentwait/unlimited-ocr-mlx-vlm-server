"""Bridge to the vendored Unlimited-OCR-MLX engine (HF repo, git submodule)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VENDOR_DIR = _REPO_ROOT / "vendor" / "Unlimited-OCR-MLX"


def import_vendor_package(vendor_dir: str | Path):
    """Import the HF repo root as package `unlimited_ocr_mlx`.

    The vendored repo is a *flat* package (``__init__.py`` + ``config.py`` +
    ``model.py`` ... at the repo root, using relative imports). The directory
    name contains dashes so it cannot be imported normally; register it under
    a proper package name instead.
    """
    vendor_dir = Path(vendor_dir).expanduser().resolve()
    init = vendor_dir / "__init__.py"
    if not init.is_file():
        raise RuntimeError(
            f"vendor code not found at {vendor_dir} (expected __init__.py); "
            "run `git submodule update --init vendor/Unlimited-OCR-MLX`"
        )
    name = "unlimited_ocr_mlx"
    existing = sys.modules.get(name)
    if existing is not None and getattr(existing, "__path__", None):
        return existing
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(vendor_dir)]
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot build import spec for {vendor_dir}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class OcrEngine:
    """Loads the vendored UnlimitedOCRInference once; infers on image files."""

    def __init__(
        self,
        model_dir: str | Path,
        vendor_dir: str | Path = DEFAULT_VENDOR_DIR,
    ):
        self.model_dir = Path(model_dir).expanduser().resolve()
        self.vendor_dir = Path(vendor_dir).expanduser().resolve()
        self._engine: Any = None

    @property
    def loaded(self) -> bool:
        return self._engine is not None

    def load(self) -> None:
        if self.loaded:
            return
        if not (self.model_dir / "model.safetensors").is_file():
            raise RuntimeError(
                f"model weights not found at {self.model_dir}/model.safetensors — "
                "run `uv run scripts/download_model.py` first (see README)"
            )
        pkg = import_vendor_package(self.vendor_dir)
        self._engine = pkg.UnlimitedOCRInference(str(self.model_dir))
        self._engine.load()

    def infer_image_file(
        self,
        image_path: str,
        *,
        prompt: str,
        max_length: int,
        temperature: float,
        base_size: int,
        image_size: int,
        crop_mode: bool,
    ) -> str:
        if not self.loaded:
            self.load()
        return self._engine.infer_single(
            image_path=image_path,
            prompt=prompt,
            max_length=max_length,
            temperature=temperature,
            base_size=base_size,
            image_size=image_size,
            crop_mode=crop_mode,
        )

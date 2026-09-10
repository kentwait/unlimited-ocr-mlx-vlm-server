"""PP-DocLayout-S (ONNX) figure region detection over rendered pages.

The vendored model (see models/MODEL_INFO.md) is a PicoDet-S layout
detector. Only the `image` and `chart` classes are consumed: figure spans
carry the cropped pixels, everything else (text, headers, tables, ...) is
already covered by the native pymupdf4llm extraction.

Detection is deliberately conservative: small regions (page rules, stray
lines) and low-confidence boxes are dropped, and overlapping boxes are
deduplicated in favour of the larger region.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: Class list, index order (PaddlePaddle/PP-DocLayout-S inference.yml).
LABELS: tuple[str, ...] = (
    "paragraph_title",
    "image",
    "text",
    "number",
    "abstract",
    "content",
    "figure_title",
    "formula",
    "table",
    "table_title",
    "reference",
    "doc_title",
    "footnote",
    "header",
    "algorithm",
    "footer",
    "seal",
    "chart_title",
    "chart",
    "formula_number",
    "header_image",
    "footer_image",
    "aside_text",
)

#: Only these classes become figure spans.
CAPTURE_CLASSES = frozenset({"image", "chart"})

#: Minimum detection score and minimum box dimension (0-1000 units).
#: 0.3 matches the base model's NMS score_threshold; real journal figures
#: land as low as ~0.5 on the bundled checkpoint, so a 0.5 cut would drop
#: them (observed on the Science fixture: full-page figure scored 0.498).
SCORE_MIN = 0.3
MIN_DIM = 60

#: Overlapping boxes above this IoU (or contained) are deduplicated.
DEDUPE_IOU = 0.7

#: A region covering more than this share of the page is a detection
#: artifact on a text page (whole-page "image" boxes), not a figure.
MAX_AREA_SHARE = 0.8

#: Model input geometry (from the base model's inference.yml).
INPUT_SIZE = 480
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)

#: Bundled model asset; override with OCR_LAYOUT_MODEL / --layout-model.
MODEL_PATH = Path(__file__).parent / "models" / "pp_doclayout_s.onnx"


@dataclass(frozen=True)
class FigureRegion:
    page: int
    box: list[int]  # 0-1000 ints
    kind: str  # "image" | "chart"
    score: float


def _iou(a: list[int], b: list[int]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _center_inside(inner: list[int], outer: list[int]) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _clamp_box(box: list[float], width: int, height: int) -> list[int]:
    """Pixel box -> clamped 0-1000 ints (axis-sorted, inversion-repaired)."""
    if width <= 0 or height <= 0:
        return [0, 0, 0, 0]
    xs = sorted((box[0] / width * 1000.0, box[2] / width * 1000.0))
    ys = sorted((box[1] / height * 1000.0, box[3] / height * 1000.0))

    def clamp(value: float) -> int:
        return max(0, min(1000, int(round(value))))

    return [clamp(xs[0]), clamp(ys[0]), clamp(xs[1]), clamp(ys[1])]


def clean_regions(
    rows: list[list[float]], page: int, width: int, height: int
) -> list[FigureRegion]:
    """Filter and dedupe raw ONNX rows into figure regions.

    Rows are `[class_id, score, x1, y1, x2, y2]` in original image pixels
    (the graph applies `scale_factor`). Kept regions are sorted by area
    descending, so the larger of two overlapping detections survives.
    """
    candidates: list[FigureRegion] = []
    for row in rows:
        class_id, score = int(row[0]), float(row[1])
        if not 0 <= class_id < len(LABELS):
            continue
        kind = LABELS[class_id]
        if kind not in CAPTURE_CLASSES or score < SCORE_MIN:
            continue
        box = _clamp_box(row[2:6], width, height)
        if min(box[2] - box[0], box[3] - box[1]) < MIN_DIM:
            continue
        area_share = ((box[2] - box[0]) / 1000.0) * ((box[3] - box[1]) / 1000.0)
        if area_share > MAX_AREA_SHARE:
            continue
        candidates.append(FigureRegion(page=page, box=box, kind=kind, score=score))

    candidates.sort(
        key=lambda r: (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]), reverse=True
    )
    kept: list[FigureRegion] = []
    for region in candidates:
        if any(
            _iou(region.box, other.box) > DEDUPE_IOU
            or _center_inside(region.box, other.box)
            for other in kept
        ):
            continue
        kept.append(region)
    return kept


class LayoutModel:
    """Lazy ONNX runtime wrapper for the bundled PP-DocLayout-S model."""

    def __init__(self, model_path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(model_path) if model_path else MODEL_PATH
        self._session = None

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def loaded(self) -> bool:
        return self._session is not None

    def load(self) -> "LayoutModel":
        if self._session is None:
            import onnxruntime as ort

            self._session = ort.InferenceSession(
                str(self.path), providers=["CPUExecutionProvider"]
            )
        return self

    def detect(self, image_path: str | os.PathLike[str], page: int) -> list[FigureRegion]:
        """Run detection on one rendered page image."""
        import numpy as np
        from PIL import Image

        self.load()
        assert self._session is not None  # narrowed by load()
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            width, height = rgb.size
            array = (
                np.asarray(rgb.resize((INPUT_SIZE, INPUT_SIZE)), dtype=np.float32)
                / 255.0
            )
        array = (array - np.array(MEAN, np.float32)) / np.array(STD, np.float32)
        array = np.ascontiguousarray(array.transpose(2, 0, 1)[None])
        scale_factor = np.array(
            [[INPUT_SIZE / height, INPUT_SIZE / width]], np.float32
        )
        boxes, _count = self._session.run(
            None, {"image": array, "scale_factor": scale_factor}
        )
        return clean_regions(boxes.tolist(), page, width, height)

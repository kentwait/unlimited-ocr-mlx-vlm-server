"""Figure crops: page render region -> inline PNG data URI.

Figure spans carry the image inline so the spans sidecar stays
self-contained (no sibling files to manage or clean up). `page` and `box`
stay on the span too, so a consumer can reconstitute or re-crop the image
from the source PDF without the payload.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

#: Longest crop edge (px) after downscaling; keeps data URIs bounded even
#: when the render DPI is raised.
MAX_CROP_PX = 2000

DATA_URI_PREFIX = "data:image/png;base64,"


def crop_data_uri(image_path: str | Path, box: list[int]) -> str | None:
    """Crop `box` (0-1000 ints) out of a rendered page PNG.

    Returns a PNG data URI, or None when the box is degenerate/unreadable.
    Never raises: crop failures degrade to a figure span without pixels.
    """
    from PIL import Image

    x1, y1, x2, y2 = box
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            left = max(0, min(width, round(x1 / 1000 * width)))
            top = max(0, min(height, round(y1 / 1000 * height)))
            right = max(0, min(width, round(x2 / 1000 * width)))
            bottom = max(0, min(height, round(y2 / 1000 * height)))
            if right - left < 1 or bottom - top < 1:
                return None
            crop = img.convert("RGB").crop((left, top, right, bottom))
        longest = max(crop.size)
        if longest > MAX_CROP_PX:
            ratio = MAX_CROP_PX / longest
            crop = crop.resize(
                (
                    max(1, round(crop.width * ratio)),
                    max(1, round(crop.height * ratio)),
                )
            )
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG", optimize=True)
    except (OSError, ValueError):
        return None
    return DATA_URI_PREFIX + base64.b64encode(buffer.getvalue()).decode("ascii")

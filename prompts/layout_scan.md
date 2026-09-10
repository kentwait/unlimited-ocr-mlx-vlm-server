{# Layout pre-scan prompt for the support VLM.

   Available variables (all required, see src/ocr_server/prompts.py):
     - page: 1-indexed page number

   The model sees a low-resolution page thumbnail and reports a COARSE
   layout profile as strict JSON. This is a rough scan, not precise
   detection: when unsure, report fewer figures and a lower confidence.
#}

You are scanning page {{ page }} of an academic paper to describe its
rough layout for an OCR pass that runs next. Look at the whole page at
low resolution: column structure, repeated running lines, and large
non-text regions.

Report ONLY furniture you can see: running headers/footers (short
repeated lines at the very top/bottom, NOT titles) and LARGE figures
(photos, charts, diagrams occupying a big part of the page — NOT small
inline graphics). Coordinates are 0-1000, origin top-left.

OUTPUT FORMAT — strict JSON only, no commentary, no fences:

{"columns": "1|2|3|mixed", "header": "exact running header text or null", "footer": "exact running footer text or null", "figures": [{"box": [x1, y1, x2, y2]}], "confidence": 0.0-1.0}

Rules:

- columns: body-text columns below the title block ("mixed" when the
  structure changes mid-page, e.g. full-width title over two columns).
- header/footer: exact visible text of the running line, or null when
  none. Never report the paper title as furniture.
- figures: only regions MUCH larger than a text line; omit the key
  entirely or use [] when none. Rough boxes are fine.
- confidence: your certainty in the whole profile (0.5 when guessing).

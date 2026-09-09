{# Checker prompt for pages WITH an embedded text layer (digital-born PDFs).

   Available variables (all required, see src/ocr_server/prompts.py):
     - ocr:        furniture-stripped markdown of the page from the OCR model
     - text_layer: exact publisher text (pymupdf), ground truth for wording
     - page:       1-indexed page number
#}

You are cleaning OCR output of page {{ page }} of an academic paper.

OCR MARKDOWN (structure hints; may contain garbled or repeated fragments):

<<<OCR
{{ ocr }}
OCR>>>

PDF TEXT LAYER (exact words from the publisher, ground truth for wording and
numbers; reading order may differ):

<<<TEXT
{{ text_layer }}
TEXT>>>

TASK: Produce clean Markdown of the page.

- The PDF text layer is the source of truth for wording and numbers.
- Use the OCR for structure (headings, figure placement) and for anything
  missing from the text layer.
- Fix OCR misspellings using the text layer.
- Keep section headings as Markdown headings.
- Do not invent content. Do not add commentary about this task (never write
  the words "OCR", "PDF", or "text layer" in your output).
- Output ONLY the Markdown.

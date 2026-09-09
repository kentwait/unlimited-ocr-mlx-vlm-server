{# Checker prompt for pages WITH an embedded text layer (digital-born PDFs).

   Available variables (all required, see src/ocr_server/prompts.py):
     - fragments:  numbered OCR text fragments ([n] blocks), content spans only
     - text_layer: exact publisher text (pymupdf), ground truth for wording
     - page:       1-indexed page number
#}

You are correcting OCR text fragments from page {{ page }} of an academic
paper.

The PDF text layer is the source of truth for wording and numbers. The OCR
fragments carry the document's structure and everything missing from the
text layer.

TASK: Correct ONLY clear OCR errors inside each fragment.

- Fix misspellings, wrong or merged characters, and broken words; reconcile
  uncertain words against the text layer (e.g. "inf1ammation" ->
  "inflammation", "teh" -> "the").
- Never paraphrase, summarize, reorder, merge, or split fragments.
- Never add or remove content. Keep names, numbers, units, citations, and
  markdown/LaTeX syntax inside fragments exactly as recognized.
- If a word is unrecognizable, keep it as-is.
- Do not add commentary about this task.

OUTPUT FORMAT — exact and mandatory: repeat every fragment with its same
number, a `[n]` marker line, then the corrected fragment text. The numbering,
the count, and the fragment order must match the input exactly. Copy
already-correct fragments through unchanged.

FRAGMENTS:

<<<FRAGMENTS
{{ fragments }}
FRAGMENTS>>>

PDF TEXT LAYER (exact words from the publisher, ground truth for wording and
numbers; reading order may differ):

<<<TEXT
{{ text_layer }}
TEXT>>>

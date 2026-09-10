{# Checker prompt for scanned pages WITHOUT a text layer.

   Available variables (all required, see src/ocr_server/prompts.py):
     - fragments: numbered OCR text fragments ([n] blocks), content spans only
     - page:      1-indexed page number
#}

You are correcting OCR text fragments from page {{ page }} of a scanned
document. No digital text layer is available.

TASK: Correct ONLY obvious OCR errors that context makes unambiguous.

- Fix misspellings, wrong or merged characters, and broken words
  (e.g. "inf1ammation" -> "inflammation", "teh" -> "the").
- Never paraphrase, summarize, reorder, merge, or split fragments.
- Never add or remove content. Keep all wording, names, numbers, units,
  citations, and markdown/LaTeX syntax inside fragments exactly as
  recognized. If a word is unrecognizable, keep it as-is.
- Do not add commentary about this task.

OUTPUT FORMAT — exact and mandatory: repeat every fragment with its same
number, a `[n]` marker line, then the corrected fragment text. The numbering,
the count, and the fragment order must match the input exactly. Copy
already-correct fragments through unchanged.

FRAGMENTS:

<<<FRAGMENTS
{{ fragments }}
FRAGMENTS>>>

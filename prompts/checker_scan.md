{# Checker prompt for scanned pages WITHOUT a text layer.

   Available variables (all required, see src/ocr_server/prompts.py):
     - ocr:  furniture-stripped markdown of the page from the OCR model
     - page: 1-indexed page number
#}

You are proofreading OCR output of page {{ page }} of a scanned document.

OCR MARKDOWN:

<<<OCR
{{ ocr }}
OCR>>>

TASK: Produce clean Markdown of the page.

- Fix obvious OCR misspellings and garbled words using context
  (e.g. "inf1ammation" -> "inflammation", "teh" -> "the").
- Keep all wording, names, numbers, and units exactly as recognized —
  never paraphrase, summarize, or add content.
- If a word is unrecognizable, keep it as-is.
- Keep section headings as Markdown headings.
- Do not add commentary about this task (never write the words "OCR" or
  "proofread" in your output).
- Output ONLY the Markdown.

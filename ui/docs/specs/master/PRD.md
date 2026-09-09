# Master PRD: OCR Library

- Status: Vision
- Owner: Maintainers

## Problem

Researchers working through OCR'd paper libraries juggle three disconnected
views: the folder of PDFs, the rendered pages, and the extracted markdown.
Checking OCR quality means switching tools and losing your place.

## Vision

A desktop companion to the unlimited-ocr server that keeps those three views
in one window and in sync: pick a PDF in the library tree, read the page and
its markdown side by side, run OCR from the same toolbar, and have the results
saved next to the PDF for the next session.

## Principles

- One window, three panes: tree, page preview, markdown — page sync keeps them
  aligned.
- Sidecars over databases: `<stem>.md` and `<stem>.spans.jsonl` live next to
  their PDFs, human-readable and portable.
- The server does the heavy work (render, OCR, furniture removal, cleanup);
  the app orchestrates jobs and owns presentation.
- Degrade gracefully: missing sidecars or anchors disable sync, never the app.
- Validate every untrusted runtime boundary (Tauri payloads, server responses).

## Capability Horizons

- Library browsing with OCR-status badges (implemented).
- Page-synced PDF/markdown reading with span overlays (implemented).
- In-app OCR jobs with progress and sidecar save (implemented).
- Markdown editing with write-back (deferred).
- Multi-column reflow-aware sync (deferred).

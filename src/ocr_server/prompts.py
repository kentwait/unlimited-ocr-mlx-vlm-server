"""Prompt templates: Markdown + Jinja2, loaded once at server startup.

Prompts live in ``prompts/*.md`` — plain Markdown files with Jinja2
expressions, passed to the model verbatim (LLMs read Markdown natively; the
formatting is for humans and the model alike). To change a prompt, edit the
file and restart the server.

Variables available to templates (rendered with StrictUndefined — a missing
or misspelled variable is a startup error, not an empty string in a prompt):
    ocr         furniture-stripped markdown of the page from the OCR model
    text_layer  pymupdf text layer (digital pages; not provided for scans)
    page        1-indexed page number

Every template is compiled and dry-rendered at load time so a bad template
fails the server start with a clear message instead of a mid-request 500.
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template, TemplateError

log = logging.getLogger("ocr_server")

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

# name -> (filename, required context keys)
TEMPLATE_SPECS = {
    "checker_digital": ("checker_digital.md", {"fragments", "text_layer", "page"}),
    "checker_scan": ("checker_scan.md", {"fragments", "page"}),
}


class PromptRegistry:
    def __init__(self, prompts_dir: str | Path = PROMPTS_DIR):
        self.prompts_dir = Path(prompts_dir)
        self._env = Environment(
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            autoescape=False,  # prompts, not HTML
        )
        self._templates: dict[str, Template] = {}

    def load(self) -> None:
        if not self.prompts_dir.is_dir():
            raise RuntimeError(f"prompts directory not found: {self.prompts_dir}")
        for name, (filename, keys) in TEMPLATE_SPECS.items():
            path = self.prompts_dir / filename
            if not path.is_file():
                raise RuntimeError(f"prompt template missing: {path}")
            try:
                tpl = self._env.from_string(path.read_text(encoding="utf-8"))
            except TemplateError as exc:
                raise RuntimeError(f"Jinja syntax error in {path}: {exc}") from exc
            # Dry-render with dummy values: catches unknown variables and
            # other runtime template errors at startup, not mid-request.
            dummy = {k: f"<DUMMY_{k.upper()}>" for k in keys}
            try:
                rendered = tpl.render(**dummy)
            except TemplateError as exc:
                raise RuntimeError(
                    f"prompt template {path} failed dry-render: {exc}\n"
                    f"available variables: {sorted(keys)}"
                ) from exc
            if not rendered.strip():
                raise RuntimeError(f"prompt template {path} renders to empty string")
            self._templates[name] = tpl
            log.info("prompt loaded: %s (%s, %d chars dry-rendered)", name, filename, len(rendered))

    def render(self, name: str, **ctx) -> str:
        tpl = self._templates.get(name)
        if tpl is None:
            raise RuntimeError(f"prompt '{name}' not loaded (server startup incomplete?)")
        return tpl.render(**ctx)

    @property
    def loaded(self) -> bool:
        return bool(self._templates)

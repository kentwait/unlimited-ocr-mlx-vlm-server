# OCR server task entry points. Coverage floors and mutation runs live
# here (manual `make mutate` only — never CI); see tests/README.md.
.PHONY: test coverage mutate hypothesis

test:
	uv run pytest

coverage:
	uv run pytest --cov=src/ocr_server --cov-report=term-missing --cov-fail-under=95

mutate:
	uv run mutmut run

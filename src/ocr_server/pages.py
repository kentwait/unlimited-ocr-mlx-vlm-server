"""Parse `pages` form values ("all", "1-3,5") into 1-indexed page numbers."""

from __future__ import annotations


def parse_pages_spec(spec: str | None, total: int) -> list[int]:
    """Return a sorted, deduped list of 1-indexed page numbers.

    Raises ValueError on out-of-range or malformed specs.
    """
    s = (spec or "all").strip().lower()
    if s in ("", "all", "*"):
        if total <= 0:
            raise ValueError("document has no pages")
        return list(range(1, total + 1))

    out: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a_str, b_str = part.split("-", 1)
                a, b = int(a_str), int(b_str)
            else:
                a = b = int(part)
        except ValueError as exc:
            raise ValueError(f"invalid page spec: {part!r}") from exc
        if a < 1 or b < 1 or a > b:
            raise ValueError(f"invalid page range: {part!r}")
        out.update(range(a, b + 1))

    if not out:
        raise ValueError("empty pages spec")
    pages = sorted(out)
    if pages[-1] > total:
        raise ValueError(f"page {pages[-1]} out of range (1-{total})")
    return pages

"""Shared fixtures: the committed fixture PDF plus synthetic text/image PDFs."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest

ASSETS = Path(__file__).parent / "assets"
PDF_PATH = ASSETS / "altemose2022.pdf"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from ocr_server.api import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def altemose_bytes() -> bytes:
    return PDF_PATH.read_bytes()


def make_text_pdf(n_pages: int = 1) -> bytes:
    """A tiny digital-born PDF with a text layer on every page."""
    doc = pymupdf.open()
    for i in range(n_pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"Test page {i + 1} heading")
        page.insert_text((72, 100), "Body text for extraction. " * 6)
    data = doc.tobytes()
    doc.close()
    return data


def make_image_pdf() -> bytes:
    """A scan-like PDF: one page, one raster image, no text objects."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (200, 260), (200, 120, 60)).save(buffer, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=260)
    page.insert_image(pymupdf.Rect(0, 0, 200, 260), stream=buffer.getvalue())
    data = doc.tobytes()
    doc.close()
    return data

"""Native layout extraction: pymupdf4llm labels -> span vocabulary."""

from __future__ import annotations

import json

import pymupdf

from ocr_server.native_layout import extract_boxes

from conftest import PDF_PATH, make_text_pdf


def _doc():
    return pymupdf.open(PDF_PATH)


def test_extract_boxes_on_fixture_page_one():
    doc = _doc()
    try:
        boxes = extract_boxes(doc, [1])[1]
    finally:
        doc.close()
    labels = {box.label for box in boxes}
    assert {"header", "title", "text", "picture"} <= labels
    assert [box.order for box in boxes] == list(range(len(boxes)))
    for box in boxes:
        assert box.page == 1
        x1, y1, x2, y2 = box.box
        assert 0 <= x1 <= x2 <= 1000
        assert 0 <= y1 <= y2 <= 1000
        if box.label != "picture":
            assert box.text.strip()


def test_extract_boxes_respects_page_subset():
    doc = _doc()
    try:
        boxes = extract_boxes(doc, [2])
    finally:
        doc.close()
    assert set(boxes) == {2}
    assert all(box.page == 2 for box in boxes[2])


def test_extract_boxes_maps_unknown_class_to_text(monkeypatch):
    import ocr_server.native_layout as native

    payload = {
        "pages": [
            {
                "page_number": 1,
                "width": 100.0,
                "height": 200.0,
                "boxes": [
                    {
                        "boxclass": "mystery-class",
                        "x0": 10,
                        "y0": 20,
                        "x1": 30,
                        "y1": 40,
                        "textlines": [{"spans": [{"text": "kept"}]}],
                    },
                    {
                        "boxclass": "text",
                        "x0": 0,
                        "y0": 0,
                        "x1": 0,
                        "y1": 0,
                        "textlines": [],
                    },
                    {"boxclass": "picture", "x0": 1, "y0": 2, "x1": 3, "y1": 4},
                ],
            }
        ]
    }
    monkeypatch.setattr(native.pymupdf4llm, "to_json", lambda *a, **k: json.dumps(payload))
    doc = pymupdf.open(stream=make_text_pdf(1), filetype="pdf")
    try:
        boxes = extract_boxes(doc, [1])[1]
    finally:
        doc.close()
    assert [(box.label, box.text) for box in boxes] == [
        ("text", "kept"),
        ("picture", ""),
    ]
    assert boxes[0].box == [100, 100, 300, 200]


def test_extract_boxes_accepts_dict_payload(monkeypatch):
    import ocr_server.native_layout as native

    payload = {
        "pages": [
            {
                "page_number": 1,
                "width": 100.0,
                "height": 100.0,
                "boxes": [
                    {
                        "boxclass": "text",
                        "x0": 0,
                        "y0": 0,
                        "x1": 50,
                        "y1": 50,
                        "textlines": [{"spans": [{"text": "hello"}]}],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(native.pymupdf4llm, "to_json", lambda *a, **k: payload)
    doc = pymupdf.open(stream=make_text_pdf(1), filetype="pdf")
    try:
        boxes = extract_boxes(doc, [1])[1]
    finally:
        doc.close()
    assert boxes[0].text == "hello"

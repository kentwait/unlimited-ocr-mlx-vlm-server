# Vendored layout model: PP-DocLayout-S (ONNX)

| | |
|---|---|
| File | `pp_doclayout_s.onnx` (4,917,852 bytes) |
| SHA256 | `33688dbee1c23e34b81777e97cb428eb40f24b242c02b5f623484959e830aec8` |
| Source | <https://huggingface.co/stefanj0/PP-DocLayout-S-ONNX> (`pp_doclayout_s.onnx`), ONNX export of `PaddlePaddle/PP-DocLayout-S` |
| Base weights | <https://huggingface.co/PaddlePaddle/PP-DocLayout-S> — Apache-2.0 |
| Architecture | PicoDet-S (GFL), 480x480 input, 23 classes |
| Purpose | Figure/table region detection on rendered page images. Only the `image` and `chart` classes are consumed (see `pp_layout.py`). |

## Preprocessing (from the base model's `inference.yml`)

1. Resize the RGB page image to 480x480 (aspect ratio not preserved).
2. Scale by 1/255, normalize with mean `[0.485, 0.456, 0.406]`, std `[0.229, 0.224, 0.225]`.
3. Transpose to CHW, float32. The second input `scale_factor` is `[480/height, 480/width]`; output boxes are in original image pixels.

## Class list (index order)

paragraph_title, image, text, number, abstract, content, figure_title, formula,
table, table_title, reference, doc_title, footnote, header, algorithm, footer,
seal, chart_title, chart, formula_number, header_image, footer_image, aside_text

## Updating

Replace the file, update the SHA256 above, and run the test suite. The
`test_pp_models.py::test_vendored_model_sha` test pins the digest so an
accidental swap is caught.

"""Bridge to the mlx-vlm Unlimited-OCR engine (DeepSeek-OCR lineage).

Model: sahilchachra/unlimited-ocr-mxfp8-mlx — block-float MXFP8 quantization of
baidu/Unlimited-OCR (config model_type "deepseekocr"), served through
mlx_vlm.load / mlx_vlm.stream_generate.

Parameter flow (traced in installed mlx_vlm): generate(**kwargs) ->
prepare_inputs -> process_inputs -> DeepseekOCRProcessor.process, which accepts
base_size / image_size / cropping and applies the gundam (crop) or base
resolution mode. apply_chat_template inserts the literal <image> token for
num_images=1.

The sahilchachra repo's tokenizer.json ships a sentencepiece-style decoder
(▁->space) even though the vocab is GPT-2 byte-level (Ġ=space, Ċ=newline), so
both decode() and the streaming detokenizer emit raw 'Ġ'/'Ċ' markers and drop
real spaces. We therefore generate via stream_generate, collect token ids, and
decode them ourselves with the byte-level mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL_REF = "sahilchachra/unlimited-ocr-mxfp8-mlx"

# GPT-2 bytes_to_unicode() inverse: unicode char in vocab -> original byte.
_GPT2_BYTE_UNICHARS = (
    [chr(c) for c in range(33, 127)]
    + [chr(c) for c in range(161, 173)]
    + [chr(n) for n in range(0, 33) if n not in (0,)]
)
# Full canonical GPT-2 ordering:
_GPT2_BYTE_TO_UNICHAR = {}
_bs = (
    list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
)
_cs = _bs[:]
_n = 0
for _b in range(256):
    if _b not in _bs:
        _bs.append(_b)
        _cs.append(256 + _n)
        _n += 1
for _b, _c in zip(_bs, _cs):
    _GPT2_BYTE_TO_UNICHAR[chr(_c)] = _b


@dataclass
class InferenceStats:
    tokens: int | None = None
    tps: float | None = None
    peak_memory_gb: float | None = None


def decode_byte_level(tokenizer: Any, ids: list[int]) -> str:
    """Decode GPT-2 byte-level BPE ids to text, bypassing the broken decoder.

    Special tokens (bos/eos/pad/image/...) are dropped; content markers the
    model emits (<|det|>...<|/det|>, <PAGE>) are kept as literal text since
    they carry layout information clients may want to parse or strip.
    """
    special_ids = set()
    for attr in ("all_special_ids",):
        val = getattr(tokenizer, attr, None)
        if val:
            special_ids.update(val)
    for tid in (getattr(tokenizer, "pad_token_id", None),):
        if tid is not None:
            special_ids.add(tid)

    out = bytearray()
    for tid in ids:
        if tid in special_ids:
            continue
        tok = tokenizer.convert_ids_to_tokens(int(tid))
        if not tok:
            continue
        for ch in tok:
            b = _GPT2_BYTE_TO_UNICHAR.get(ch)
            if b is not None:
                out.append(b)
            else:
                out.extend(ch.encode("utf-8"))
    return out.decode("utf-8", errors="replace")


class OcrEngine:
    """Lazily loads the mlx-vlm model once; infers on image files."""

    def __init__(self, model_ref: str = DEFAULT_MODEL_REF):
        self.model_ref = model_ref
        self.model: Any = None
        self.processor: Any = None

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        if self.loaded:
            return
        from mlx_vlm import load

        self.model, self.processor = load(self.model_ref)

    def infer_image_file(
        self,
        image_path: str,
        *,
        prompt: str,
        max_tokens: int,
        temperature: float,
        base_size: int,
        image_size: int,
        cropping: bool,
    ) -> tuple[str, InferenceStats]:
        if not self.loaded:
            self.load()
        import time as _time

        from mlx_vlm.generate.dispatch import stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template

        formatted = apply_chat_template(
            self.processor, self.model.config, prompt, num_images=1
        )
        ids: list[int] = []
        tps = None
        peak_gb = None
        t0 = _time.perf_counter()
        for resp in stream_generate(
            self.model,
            self.processor,
            formatted,
            image=image_path,
            max_tokens=max_tokens,
            temperature=temperature,
            base_size=base_size,
            image_size=image_size,
            cropping=cropping,
        ):
            if resp.is_draft:
                continue
            if resp.token is not None:
                ids.append(int(resp.token))
            tps = resp.generation_tps
            peak_gb = resp.peak_memory
        elapsed = _time.perf_counter() - t0

        text = decode_byte_level(self.processor.tokenizer, ids).strip()
        if tps is None and elapsed > 0 and len(ids) > 0:
            tps = len(ids) / elapsed
        return text, InferenceStats(
            tokens=len(ids), tps=tps, peak_memory_gb=peak_gb
        )

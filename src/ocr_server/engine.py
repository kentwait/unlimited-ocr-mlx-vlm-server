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
    early_stop: bool = False


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


def _dedupe_long_lines(text: str, min_len: int = 40) -> str:
    """Drop exact-duplicate long lines (loop remnants), keep first occurrence.

    Repetition loops that escape the token-level break leave duplicated lines
    in decoded text. Within a single page, identical long lines are
    pathological; short lines (headers, numbers) are kept as-is.
    """
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= min_len:
            if key in seen:
                continue
            seen.add(key)
        out.append(line)
    return "\n".join(out)


def _loop_period(
    tokens: list[int],
    *,
    max_period: int = 32,
    check_len: int = 96,
    threshold: float = 0.95,
) -> int | None:
    """Return the period if the token tail is near-periodic, else None.

    DeepSeek-OCR-style decoders degenerate into tight repetition loops on
    dense/sparse-edge pages. Upstream's n-gram guard (n=35) only breaks
    long-period repeats; short-period loops (repeated fragments, `89.89.89`,
    `\\\\( \\\\alpha \\\\)` runs) never complete an exact 35-gram. Checking the
    last `check_len` tokens for agreement with a p-shifted copy catches all
    periods <= max_period cheaply on plain Python ints (no GPU sync).
    """
    n = len(tokens)
    if n < check_len + max_period:
        return None
    recent = tokens[-check_len:]
    for p in range(1, max_period + 1):
        shifted = tokens[-check_len - p:-p]
        agree = sum(1 for x, y in zip(recent, shifted) if x == y)
        if agree >= threshold * check_len:
            return p
    return None


class OcrEngine:
    """Lazily loads the mlx-vlm model once; infers on image files."""

    def __init__(self, model_ref: str = DEFAULT_MODEL_REF):
        self.model_ref = model_ref
        self.model: Any = None
        self.processor: Any = None

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:  # pragma: no cover - downloads/loads MLX weights
        # pragma: no mutate block - requires MLX weights
        if self.loaded:
            return
        from mlx_vlm import load

        self.model, self.processor = load(self.model_ref)

    def infer_image_file(  # pragma: no cover - runs the MLX model
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
        # pragma: no mutate block - requires MLX weights
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
        loop_period: int | None = None
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
                # Cheap near-periodicity check every 16 tokens; break out of
                # degenerate repetition loops instead of burning max_tokens.
                if len(ids) % 16 == 0:
                    p = _loop_period(ids)
                    if p is not None:
                        loop_period = p
                        break
            tps = resp.generation_tps
            peak_gb = resp.peak_memory
        elapsed = _time.perf_counter() - t0

        if loop_period is not None:
            # Trim the loop tail: drop tokens past where the loop stabilized.
            keep = len(ids) - 4 * (loop_period + 16)
            ids = ids[: max(0, keep)]
        text = decode_byte_level(self.processor.tokenizer, ids).strip()
        text = _dedupe_long_lines(text)
        if tps is None and elapsed > 0 and len(ids) > 0:
            tps = len(ids) / elapsed
        return text, InferenceStats(
            tokens=len(ids),
            tps=tps,
            peak_memory_gb=peak_gb,
            early_stop=loop_period is not None,
        )

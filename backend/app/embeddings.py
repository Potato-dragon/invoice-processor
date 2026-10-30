"""Small local text embeddings (fastembed, ONNX, 384 dims). No API quota used.

The model (BAAI/bge-small-en-v1.5, ~67 MB) is baked into the Docker image.
If it cannot load, a deterministic hashed bag-of-words vector is used so the
system keeps working (search quality drops; a warning is logged once).
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import threading

logger = logging.getLogger(__name__)

DIMS = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model = None
_lock = threading.Lock()
_failed = False


def _get_model():  # noqa: ANN202
    global _model, _failed
    if _model is None and not _failed:
        with _lock:
            if _model is None and not _failed:
                try:
                    from fastembed import TextEmbedding

                    _model = TextEmbedding(MODEL_NAME)
                except Exception:  # noqa: BLE001
                    logger.warning("fastembed model unavailable; using hashed embeddings", exc_info=True)
                    _failed = True
    return _model


def _hashed(text: str) -> list[float]:
    vec = [0.0] * DIMS
    for tok in re.findall(r"\w+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % DIMS] += 1.0 if (h >> 9) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    if model is None:
        return [_hashed(t) for t in texts]
    # bge vectors are unit length, so L2 distance ranks the same as cosine.
    return [list(map(float, v)) for v in model.embed(texts)]


def embed_query(text: str) -> list[float]:
    model = _get_model()
    if model is None:
        return _hashed(text)
    return [float(x) for x in next(iter(model.query_embed(text)))]

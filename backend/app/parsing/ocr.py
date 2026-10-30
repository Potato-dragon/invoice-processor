"""OCR for one page image: OpenCV cleanup, then Tesseract with word confidences."""
from __future__ import annotations

import logging
import os

import cv2
import numpy as np
import pytesseract

logger = logging.getLogger(__name__)

# English only by default: adding fra+deu+spa made OCR ~20x slower in tests
# (15 s vs 0.7 s per page) for little gain on Latin-script invoices.
_LANGS = os.getenv("OCR_LANGS", "eng")
_TIMEOUT_S = 60
_MAX_SKEW_DEG = 10.0


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        return cv2.cvtColor(img, cv2.COLOR_RGBA2GRAY)
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def estimate_skew(gray: np.ndarray) -> float:
    """Angle in degrees that text lines are rotated by (0 if unsure).

    Uses the minimum-area rectangle around dark pixels on a downscaled copy;
    cheap and good enough for scanner skew up to about 10 degrees.
    """
    scale = 1000 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    _, bw = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Merge characters into line blobs so the rectangle follows text lines.
    bw = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    coords = np.column_stack(np.where(bw > 0))
    if len(coords) < 200:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    # OpenCV versions differ: [-90, 0) or (0, 90]. Map to (-45, 45].
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90
    return float(angle) if abs(angle) <= _MAX_SKEW_DEG else 0.0


def _rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess(img: np.ndarray) -> np.ndarray:
    """Grayscale, deskew, light denoise, then binarise with Otsu."""
    gray = _to_gray(img)
    angle = estimate_skew(gray)
    if abs(angle) >= 0.3:
        gray = _rotate(gray, angle)
    gray = cv2.medianBlur(gray, 3)
    # Global Otsu threshold: picks the ink/paper split per page, so it also
    # handles faded scans. (CLAHE before Otsu amplified noise in tests.)
    _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray


def _upscale_if_small(gray: np.ndarray, dpi_hint: int | None) -> np.ndarray:
    # Tesseract likes ~300 DPI; upscale low-resolution images.
    if dpi_hint and dpi_hint < 250:
        f = min(2.0, 300 / dpi_hint)
        return cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return gray


def ocr_image(img: np.ndarray, dpi_hint: int | None = None) -> tuple[str, float]:
    """Return (text, confidence 0..1). Raises on Tesseract failure/timeout."""
    gray = _upscale_if_small(preprocess(img), dpi_hint)
    data = pytesseract.image_to_data(
        gray, lang=_LANGS, config="--psm 3", output_type=pytesseract.Output.DICT, timeout=_TIMEOUT_S
    )
    lines: list[str] = []
    current: tuple[int, int, int] | None = None
    words: list[str] = []
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != current:
            if words:
                lines.append(" ".join(words))
            words, current = [], key
        word = (word or "").strip()
        if not word:
            continue
        words.append(word)
        conf = float(data["conf"][i])
        if conf >= 0:
            confs.append(conf)
    if words:
        lines.append(" ".join(words))
    confidence = round(sum(confs) / len(confs) / 100, 3) if confs else 0.0
    return "\n".join(lines), confidence

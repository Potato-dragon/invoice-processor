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


def deskew(img: np.ndarray) -> np.ndarray:
    gray = _to_gray(img)
    angle = estimate_skew(gray)
    return _rotate(gray, angle) if abs(angle) >= 0.3 else gray


def preprocess(img: np.ndarray, mode: str = "fast") -> np.ndarray:
    """Deskewed grayscale page, cleaned for Tesseract.

    fast:   median denoise + global Otsu threshold. Good for clean and fair scans.
    rescue: contrast stretch + non-local-means denoise, no threshold. For faded,
            noisy scans where Otsu drops light-grey text (used as a retry).
    """
    gray = deskew(img)
    if mode == "rescue":
        lo, hi = np.percentile(gray, 1), np.percentile(gray, 99.5)
        gray = np.clip((gray.astype(np.float32) - lo) * 255 / max(1.0, hi - lo), 0, 255).astype(np.uint8)
        return cv2.fastNlMeansDenoising(gray, None, 15, 7, 21)
    gray = cv2.medianBlur(gray, 3)
    # (CLAHE before Otsu amplified noise in tests, so it is not used.)
    _, gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return gray


TARGET_LONG_SIDE = 3000  # px: roughly an A4 page at 250-300 DPI


def _upscale_if_small(gray: np.ndarray, dpi_hint: int | None) -> np.ndarray:
    """Tesseract needs text around 20-30 px tall; enlarge low-resolution images.

    Uses the declared DPI when present, otherwise the pixel size: screenshots
    and phone exports often carry no DPI (a 497 x 706 px invoice was never
    upscaled before this check).
    """
    f = 1.0
    if dpi_hint and dpi_hint < 250:
        f = min(2.0, 300 / dpi_hint)
    elif not dpi_hint and max(gray.shape) < 0.6 * TARGET_LONG_SIDE:
        f = min(4.0, TARGET_LONG_SIDE / max(gray.shape))
    if f > 1.0:
        return cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return gray


def _rows_from_words(data: dict) -> list[str]:
    """Rebuild reading order from word boxes.

    Tesseract's own blocks follow columns, which separates a label ("Total:")
    from its right-aligned value. Here words on the same visual row form one
    line; a wide horizontal gap starts a new cell, and cells are joined with a
    tab so the extractor can tell "label | value" and two-column headers apart.
    """
    words = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if not text or float(data["conf"][i]) < 0:
            continue
        words.append((data["top"][i], data["left"][i], data["width"][i], data["height"][i], text))
    return rows_from_boxes(words)


def rows_from_boxes(words: list[tuple]) -> list[str]:
    """Group (top, left, width, height, text) word boxes into tab-separated rows.

    Shared by OCR and the PDF text layer, whose stored text order is
    arbitrary (a value is often stored before its label).
    """
    if not words:
        return []
    heights = sorted(w[3] for w in words)
    h = max(1, heights[len(heights) // 2])
    rows: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: (w[0] + w[3] / 2, w[1])):
        cy = w[0] + w[3] / 2
        if rows and abs(cy - rows[-1][0][0]) <= 0.6 * h:
            rows[-1][1].append(w)
        else:
            rows.append([(cy,), [w]])
    out = []
    for _, row in rows:
        row.sort(key=lambda w: w[1])
        cells, cell, prev_right = [], [], None
        for top, left, width, height, text in row:
            if prev_right is not None and left - prev_right > 1.8 * h:
                cells.append(" ".join(cell))
                cell = []
            cell.append(text)
            prev_right = left + width
        cells.append(" ".join(cell))
        out.append("\t".join(cells))
    return out


RESCUE_BELOW = 0.75


def _run(gray: np.ndarray) -> tuple[str, float]:
    data = pytesseract.image_to_data(
        gray, lang=_LANGS, config="--psm 3", output_type=pytesseract.Output.DICT, timeout=_TIMEOUT_S
    )
    confs = [float(c) for c, t in zip(data["conf"], data["text"]) if float(c) >= 0 and (t or "").strip()]
    confidence = round(sum(confs) / len(confs) / 100, 3) if confs else 0.0
    return "\n".join(_rows_from_words(data)), confidence


def ocr_image(img: np.ndarray, dpi_hint: int | None = None) -> tuple[str, float]:
    """Return (text, confidence 0..1). Raises on Tesseract failure/timeout.

    A fast pass first; if its confidence is low, a slower rescue pass, and the
    better of the two (by mean word confidence) is kept.
    """
    img = _upscale_if_small(_to_gray(img), dpi_hint)
    text, conf = _run(preprocess(img, "fast"))
    if conf < RESCUE_BELOW:
        text2, conf2 = _run(preprocess(img, "rescue"))
        if conf2 > conf:
            return text2, conf2
    return text, conf

"""JPG / PNG / TIFF (multi-frame) via Pillow, then OCR per frame."""
from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from app.contracts import ErrorCode, PageMethod, ParsedPage, PipelineError
from app.parsing.ocr import ocr_image


def _max_pages() -> int:
    return int(os.getenv("MAX_PAGES", "1500"))


def parse_image_pages(file_path: str, warnings: list[str]) -> list[ParsedPage]:
    if os.path.getsize(file_path) == 0:
        raise PipelineError(ErrorCode.FILE_EMPTY, "the file is empty")
    try:
        img = Image.open(file_path)
        img.verify()  # catches truncated/corrupt files early
        img = Image.open(file_path)  # verify() leaves the image unusable
    except Image.DecompressionBombError as exc:
        raise PipelineError(ErrorCode.FILE_TOO_LARGE, "image is too large to process safely") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise PipelineError(ErrorCode.FILE_CORRUPT, f"image could not be read: {exc}") from exc

    pages: list[ParsedPage] = []
    with img:
        n_frames = getattr(img, "n_frames", 1)
        if n_frames > _max_pages():
            raise PipelineError(ErrorCode.PAGE_LIMIT_EXCEEDED, f"image has {n_frames} frames; the limit is {_max_pages()}")
        for index, frame in enumerate(ImageSequence.Iterator(img)):
            page_no = index + 1
            try:
                frame = ImageOps.exif_transpose(frame)
                dpi = frame.info.get("dpi", (None,))[0]
                if frame.mode not in ("L", "RGB"):
                    frame = frame.convert("RGB")
                arr = np.asarray(frame)
                text, conf = ocr_image(arr, dpi_hint=int(dpi) if dpi else None)
            except OSError as exc:
                raise PipelineError(ErrorCode.FILE_CORRUPT, f"image frame {page_no} is damaged: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - OCR failure on one frame
                warnings.append(f"page {page_no}: OCR failed ({type(exc).__name__})")
                pages.append(ParsedPage(page_no=page_no, text="", method=PageMethod.NONE, width=frame.width, height=frame.height))
                continue
            if not text.strip():
                warnings.append(f"page {page_no}: OCR found no text")
                pages.append(ParsedPage(page_no=page_no, text="", method=PageMethod.NONE, width=frame.width, height=frame.height))
            else:
                pages.append(ParsedPage(page_no=page_no, text=text, method=PageMethod.OCR, ocr_confidence=conf, width=frame.width, height=frame.height))
    if not pages:
        raise PipelineError(ErrorCode.FILE_EMPTY, "image has no frames")
    if all(p.method == PageMethod.NONE for p in pages):
        raise PipelineError(ErrorCode.OCR_FAILED, "no text could be read from the image")
    return pages

"""PDF pages: text layer when present, OCR otherwise. Page by page, memory flat."""
from __future__ import annotations

import logging
import os
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

import pymupdf as fitz  # PyMuPDF
import numpy as np

from app.contracts import ErrorCode, PageMethod, ParsedPage, PipelineError
from app.parsing.ocr import ocr_image, rows_from_boxes

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 25
_OCR_WORKERS = int(os.getenv("OCR_WORKERS", "4"))


def _max_pages() -> int:
    return int(os.getenv("MAX_PAGES", "1500"))


def _dpi() -> int:
    return int(os.getenv("OCR_DPI", "300"))


def open_pdf(file_path: str) -> fitz.Document:
    if os.path.getsize(file_path) == 0:
        raise PipelineError(ErrorCode.FILE_EMPTY, "the file is empty")
    try:
        doc = fitz.open(file_path, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types
        raise PipelineError(ErrorCode.FILE_CORRUPT, f"PDF could not be opened: {exc}") from exc
    if doc.needs_pass or doc.is_encrypted:
        doc.close()
        raise PipelineError(ErrorCode.FILE_ENCRYPTED, "PDF is password protected")
    if doc.page_count == 0:
        repaired = doc.is_repaired
        doc.close()
        if repaired:
            raise PipelineError(ErrorCode.FILE_CORRUPT, "PDF is damaged and has no readable pages")
        raise PipelineError(ErrorCode.FILE_EMPTY, "PDF has no pages")
    if doc.page_count > _max_pages():
        n = doc.page_count
        doc.close()
        raise PipelineError(ErrorCode.PAGE_LIMIT_EXCEEDED, f"PDF has {n} pages; the limit is {_max_pages()}")
    return doc


def text_layer_rows(page: fitz.Page) -> str:
    """Text layer rebuilt in visual order: one line per row, tab between cells.

    The order stored in a PDF is whatever the generator chose; many real
    invoices store a value before its label ("993548900" then "Factuurnummer:").
    Rebuilding rows from word positions puts a label and its value side by side.
    """
    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)
    boxes = [(w[1], w[0], w[2] - w[0], w[3] - w[1], w[4]) for w in words if w[4].strip()]
    return "\n".join(rows_from_boxes(boxes))


def _render(page: fitz.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()


def _ocr_job(page_no: int, img: np.ndarray, width: int, height: int) -> ParsedPage:
    text, conf = ocr_image(img)
    return ParsedPage(page_no=page_no, text=text, method=PageMethod.OCR, ocr_confidence=conf, width=width, height=height)


def parse_pdf_pages(file_path: str, warnings: list[str]) -> list[ParsedPage]:
    doc = open_pdf(file_path)
    dpi = _dpi()
    results: dict[int, ParsedPage] = {}
    pending: deque[tuple[int, Future, int, int]] = deque()

    def _collect(block: bool) -> None:
        while pending and (block or pending[0][1].done()):
            page_no, fut, w, h = pending.popleft()
            try:
                results[page_no] = fut.result()
            except Exception as exc:  # noqa: BLE001 - one bad page must not fail the doc
                warnings.append(f"page {page_no}: OCR failed ({type(exc).__name__})")
                results[page_no] = ParsedPage(page_no=page_no, text="", method=PageMethod.NONE, width=w, height=h)

    try:
        with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
            for index in range(doc.page_count):
                page_no = index + 1
                try:
                    page = doc.load_page(index)
                    w, h = int(page.rect.width), int(page.rect.height)
                    text = page.get_text("text")
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"page {page_no}: unreadable ({type(exc).__name__})")
                    results[page_no] = ParsedPage(page_no=page_no, text="", method=PageMethod.NONE)
                    continue
                if len("".join(text.split())) >= MIN_TEXT_CHARS:
                    results[page_no] = ParsedPage(page_no=page_no, text=text_layer_rows(page) or text,
                                                  method=PageMethod.TEXT_LAYER, width=w, height=h)
                    continue
                try:
                    img = _render(page, dpi)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"page {page_no}: could not render ({type(exc).__name__})")
                    results[page_no] = ParsedPage(page_no=page_no, text="", method=PageMethod.NONE, width=w, height=h)
                    continue
                pending.append((page_no, pool.submit(_ocr_job, page_no, img, w, h), w, h))
                # Bound in-flight page images so memory stays flat on huge files.
                if len(pending) >= _OCR_WORKERS * 2:
                    _collect(block=False)
                    if len(pending) >= _OCR_WORKERS * 2:
                        page_no0, fut0, w0, h0 = pending[0]
                        fut0.exception()  # wait for the oldest
                        _collect(block=False)
            _collect(block=True)
    finally:
        doc.close()

    pages = [results[n] for n in sorted(results)]
    for i, p in enumerate(pages):
        if p.method == PageMethod.OCR and not p.text.strip():
            warnings.append(f"page {p.page_no}: OCR found no text")
            pages[i] = p.model_copy(update={"method": PageMethod.NONE, "ocr_confidence": None})
    if all(p.method == PageMethod.NONE for p in pages):
        raise PipelineError(ErrorCode.OCR_FAILED, "no text could be read from any page")
    return pages

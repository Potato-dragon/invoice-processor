"""Detect the real file type from its first bytes (never trust the extension alone)."""
from __future__ import annotations

import zipfile
from typing import BinaryIO

from app.contracts import DocumentKind, ErrorCode, PipelineError

_CSV_EXTS = (".csv", ".tsv", ".txt")


def detect(head: bytes, filename: str, fh: BinaryIO) -> tuple[DocumentKind, str]:
    """Return (kind, mime) or raise PipelineError(FILE_TYPE_UNSUPPORTED)."""
    name = (filename or "").lower()
    if head.startswith(b"%PDF-"):
        return DocumentKind.PDF, "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return DocumentKind.IMAGE, "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return DocumentKind.IMAGE, "image/png"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return DocumentKind.IMAGE, "image/tiff"
    if head.startswith(b"PK\x03\x04"):
        fh.seek(0)
        try:
            with zipfile.ZipFile(fh) as z:
                if any(n.startswith("xl/") for n in z.namelist()):
                    return DocumentKind.SPREADSHEET, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        except zipfile.BadZipFile:
            if name.endswith(".xlsx"):
                return DocumentKind.SPREADSHEET, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        raise PipelineError(ErrorCode.FILE_TYPE_UNSUPPORTED, "zip file is not an Excel workbook")
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        if name.endswith(".xls"):
            return DocumentKind.SPREADSHEET, "application/vnd.ms-excel"
        raise PipelineError(ErrorCode.FILE_TYPE_UNSUPPORTED, "legacy Office file that is not .xls")
    if name.endswith(_CSV_EXTS) and _looks_like_text(head):
        return DocumentKind.SPREADSHEET, "text/csv"
    ext = name.rsplit(".", 1)[-1] if "." in name else "unknown"
    raise PipelineError(ErrorCode.FILE_TYPE_UNSUPPORTED, f"file content does not match a supported type (.{ext})")


def _looks_like_text(head: bytes) -> bool:
    if b"\x00" in head:
        return False
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            head.decode(enc)
            return True
        except UnicodeDecodeError:
            continue
    return False

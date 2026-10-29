"""Extraction package: rules + LLM cascade to produce ExtractionResult."""
from app.extraction.extractor import extract_invoice

__all__ = ["extract_invoice"]

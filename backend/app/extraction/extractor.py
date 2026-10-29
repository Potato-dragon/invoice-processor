"""Extraction cascade: rules first, then LLM for missing/low-confidence fields.

Public API:
    extract_invoice(pages, llm_client=None, cache=None) -> ExtractionResult

Cascade logic:
1. Run rules extractor (extract_by_rules).
2. Run grounding on rules output.
3. Decide which required fields are missing or below confidence threshold.
4. If any, call primary LLM with only those fields.
5. Validate LLM response (Pydantic); if invalid, retry once (cached).
6. Run grounding on LLM output, merge (rules >= 0.7 always wins).
7. If required fields still missing, repeat with fallback model.
8. Return final ExtractionResult.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import ValidationError

from app.contracts import (
    ErrorCode,
    ExtractionMethod,
    ExtractionResult,
    ExtractedField,
    ExtractedLineItem,
    ParsedPage,
    PipelineError,
)
from app.extraction.ground import ground_result
from app.extraction.limiter import LLMCache, estimate_tokens, get_cache, get_rate_limiter
from app.extraction.llm import LLMClient, extract_json_from_text, make_llm_client
from app.extraction.prompts import REPAIR_SUFFIX, build_prompt
from app.extraction.rules import extract_by_rules

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"invoice_number", "invoice_date", "supplier_name", "total"}
_CONFIDENCE_THRESHOLD = 0.70

# Snippet sizes
_FIRST_PAGE_CHARS = 3_000
_TOTALS_AREA_CHARS = 1_500


def _get_model(env_var: str) -> str:
    model = os.getenv(env_var, "")
    if not model:
        raise PipelineError(ErrorCode.LLM_UNAVAILABLE, f"{env_var} is not set")
    return model


def _primary_model() -> str:
    return _get_model("LLM_PRIMARY_MODEL")


def _fallback_model() -> str:
    return _get_model("LLM_FALLBACK_MODEL")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _needs_llm(result: ExtractionResult) -> list[str]:
    """Return list of required fields that are null or below threshold."""
    missing: list[str] = []
    for fname in _REQUIRED_FIELDS:
        field: ExtractedField = getattr(result, fname)
        if field.value is None or field.confidence < _CONFIDENCE_THRESHOLD:
            missing.append(fname)
    return missing


def _build_doc_snippet(pages: list[ParsedPage]) -> str:
    """Build trimmed text for the LLM: first page up to 3000 chars + totals area of last page."""
    first = pages[0].text[:_FIRST_PAGE_CHARS] if pages else ""
    last_totals = ""
    if len(pages) > 1:
        last_text = pages[-1].text
        last_totals = "\n[Last page excerpt]\n" + last_text[-_TOTALS_AREA_CHARS:]
    return first + last_totals


def _parse_llm_field(raw: Any, fname: str) -> ExtractedField:
    """Convert a raw LLM dict field to ExtractedField, with fallback to empty."""
    if not isinstance(raw, dict):
        return ExtractedField(value=None, confidence=0.0, evidence=None, page=None)
    value = raw.get("value")
    evidence = raw.get("evidence")
    page = raw.get("page")
    if not isinstance(value, str):
        value = None
    if not isinstance(evidence, str) or not evidence.strip():
        evidence = None
    if not isinstance(page, int):
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
    if value is None:
        return ExtractedField(value=None, confidence=0.0, evidence=None, page=None)
    return ExtractedField(value=value, confidence=0.80, evidence=evidence, page=page)


def _parse_llm_line_items(raw: Any) -> list[ExtractedLineItem]:
    if not isinstance(raw, list):
        return []
    items: list[ExtractedLineItem] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            items.append(ExtractedLineItem(
                description=entry.get("description"),
                quantity=entry.get("quantity"),
                unit_price=entry.get("unit_price"),
                amount=entry.get("amount"),
                confidence=0.75,
                evidence=entry.get("evidence"),
                page=entry.get("page"),
            ))
        except ValidationError:
            pass
    return items


def _merge_llm_into_result(
    base: ExtractionResult,
    llm_data: dict[str, Any],
    missing_fields: list[str],
    pages: list[ParsedPage],
) -> ExtractionResult:
    """Merge LLM values into base result.

    Rules values with confidence >= 0.7 always win.
    LLM values are grounded before merging.
    """
    updates: dict[str, Any] = {}
    notes = list(base.notes)

    scalar_fields = [
        "invoice_number", "invoice_date", "supplier_name", "customer_name",
        "subtotal", "tax", "total", "currency",
    ]
    for fname in scalar_fields:
        if fname not in missing_fields:
            continue  # only update fields we asked about
        raw = llm_data.get(fname)
        llm_field = _parse_llm_field(raw, fname)
        base_field: ExtractedField = getattr(base, fname)
        if base_field.value is not None and base_field.confidence >= _CONFIDENCE_THRESHOLD:
            continue  # rules wins
        # Ground LLM field
        if llm_field.value is not None:
            from app.extraction.ground import _evidence_found  # noqa: PLC0415
            if not _evidence_found(llm_field.evidence, pages):
                notes.append(f"EVIDENCE_NOT_FOUND:{fname}")
                llm_field = ExtractedField(value=None, confidence=0.0, evidence=None, page=None)
        updates[fname] = llm_field

    # Line items: only add from LLM if rules found none
    if "line_items" in missing_fields or not base.line_items:
        raw_items = llm_data.get("line_items", [])
        llm_items = _parse_llm_line_items(raw_items)
        if llm_items:
            updates["line_items"] = llm_items

    return base.model_copy(update={**updates, "notes": notes})


# ---------------------------------------------------------------------------
# LLM call with cache + rate limiting
# ---------------------------------------------------------------------------

def _call_llm_cached(
    model: str,
    model_key: str,
    prompt: str,
    doc_text: str,
    client: LLMClient,
    cache: LLMCache,
) -> dict[str, Any]:
    # 1. Cache check
    cached = cache.get(model, prompt, doc_text)
    if cached is not None:
        logger.debug("LLM cache hit for model=%s", model)
        return cached

    # 2. Rate-limit check + reserve
    tokens = estimate_tokens(prompt)
    limiter = get_rate_limiter(model_key)
    limiter.check_and_reserve(tokens)

    # 3. Call LLM
    response = client.complete(model, prompt)

    # 4. Store in cache
    cache.set(model, prompt, doc_text, response)
    return response


def _call_with_repair(
    model: str,
    model_key: str,
    prompt: str,
    doc_text: str,
    client: LLMClient,
    cache: LLMCache,
) -> dict[str, Any]:
    """Call LLM; on invalid JSON, retry once with a repair prompt (also cached)."""
    try:
        return _call_llm_cached(model, model_key, prompt, doc_text, client, cache)
    except PipelineError as exc:
        if exc.code != ErrorCode.LLM_INVALID_OUTPUT:
            raise
        # Repair retry
        repair_prompt = prompt + REPAIR_SUFFIX
        try:
            return _call_llm_cached(model, model_key, repair_prompt, doc_text, client, cache)
        except PipelineError:
            raise PipelineError(ErrorCode.LLM_INVALID_OUTPUT, "LLM returned invalid JSON after repair retry") from None


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_invoice(
    pages: list[ParsedPage],
    *,
    llm_client: LLMClient | None = None,
    cache: LLMCache | None = None,
    session_factory: Any = None,
) -> ExtractionResult:
    """Extract invoice fields from a list of ParsedPage objects.

    Steps:
    1. Rules-based extraction + grounding.
    2. LLM primary for missing/low-confidence required fields.
    3. LLM fallback if primary fails or still leaves required fields empty.
    4. Returns ExtractionResult with correct method label.
    """
    if llm_client is None:
        llm_client = make_llm_client()
    if cache is None:
        cache = get_cache(session_factory)

    # ---- Step 1: rules ----
    result = extract_by_rules(pages)
    result = ground_result(result, pages)
    method = ExtractionMethod.RULES

    missing = _needs_llm(result)
    if not missing:
        return result.model_copy(update={"method": method})

    # ---- Step 2: LLM primary ----
    doc_snippet = _build_doc_snippet(pages)
    prompt = build_prompt(missing, doc_snippet)

    primary_failed = False
    try:
        primary = _get_model("LLM_PRIMARY_MODEL")
        llm_data = _call_with_repair(primary, "primary", prompt, doc_snippet, llm_client, cache)
        result = _merge_llm_into_result(result, llm_data, missing, pages)
        method = ExtractionMethod.LLM_PRIMARY
    except PipelineError as exc:
        logger.warning("Primary LLM failed: %s", exc)
        primary_failed = True

    # ---- Step 3: LLM fallback ----
    still_missing = _needs_llm(result)
    if still_missing and (primary_failed or still_missing):
        try:
            fallback = _get_model("LLM_FALLBACK_MODEL")
            fallback_prompt = build_prompt(still_missing, doc_snippet)
            llm_data = _call_with_repair(fallback, "fallback", fallback_prompt, doc_snippet, llm_client, cache)
            result = _merge_llm_into_result(result, llm_data, still_missing, pages)
            method = ExtractionMethod.LLM_FALLBACK
        except PipelineError as exc:
            logger.warning("Fallback LLM also failed: %s", exc)

    return result.model_copy(update={"method": method})

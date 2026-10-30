"""Validation: field, arithmetic, sanity, quality and duplicate checks; cross-checks.

Public API (CONTRACTS section 8):
    validate_invoice(extraction, pages, existing) -> list[IssueModel]
    crosscheck(left, right) -> CrosscheckResult
"""
from __future__ import annotations

from typing import Any

from app.contracts import ExtractionResult, IssueModel, IssueSeverity, ParsedPage
from app.validation.checks import check_arithmetic, check_duplicates, check_missing, check_quality, check_sanity
from app.validation.crosscheck import crosscheck, crosscheck_batch, crosscheck_issues
from app.validation.lookup import (
    ContractLookupAdapter,
    DbDuplicateLookup,
    DuplicateLookup,
    ExistingInvoice,
    InMemoryDuplicateLookup,
    normalize_supplier,
)


def validate_invoice(extraction: ExtractionResult, pages: list[ParsedPage], existing: Any = None) -> list[IssueModel]:
    lookup = existing
    if existing is not None and not hasattr(existing, "find_candidates"):
        lookup = ContractLookupAdapter(existing)
    return [
        *check_missing(extraction),
        *check_arithmetic(extraction),
        *check_sanity(extraction),
        *check_quality(extraction, pages),
        *check_duplicates(extraction, lookup),
    ]


def needs_review(issues: list[IssueModel]) -> bool:
    return any(i.severity == IssueSeverity.ERROR and not i.resolved for i in issues)


__all__ = [
    "validate_invoice", "needs_review", "crosscheck", "crosscheck_batch", "crosscheck_issues",
    "DuplicateLookup", "DbDuplicateLookup", "InMemoryDuplicateLookup", "ExistingInvoice", "normalize_supplier",
]

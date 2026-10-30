"""Cross-checks: invoice vs invoice (PDF-PDF) and invoice vs ledger rows (PDF-Excel).

Matching uses exact normalized keys only (invoice number + supplier); fields are
then compared with the money tolerance. Batch mode indexes by key (O(n)).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from app.contracts import CrosscheckKind, CrosscheckOutcome, CrosscheckResult, IssueCode, IssueModel, IssueSeverity
from app.validation.checks import TOLERANCE, _dec
from app.validation.lookup import normalize_invoice_number, normalize_supplier

_MONEY = ("total", "subtotal", "tax")
_OTHER = ("invoice_date", "currency")


def _get(item: Any, name: str) -> Any:
    """Read a field from a dict, a LedgerRow/ORM object, or an ExtractionResult."""
    if isinstance(item, dict):
        v = item.get(name)
    else:
        v = getattr(item, name, None)
    if hasattr(v, "value") and not isinstance(v, (str, Decimal)):
        v = v.value  # ExtractedField
    return v


def _ref(item: Any) -> dict[str, Any]:
    ref = {k: _get(item, k) for k in ("id", "invoice_number", "supplier_name", "sheet_name", "row_no", "document_id")}
    return {k: (str(v) if v is not None and not isinstance(v, (int, str)) else v) for k, v in ref.items() if v is not None}


def match_key(item: Any) -> tuple[str, str] | None:
    num = normalize_invoice_number(_get(item, "invoice_number"))
    if not num:
        return None
    return num, normalize_supplier(_get(item, "supplier_name"))


def _compare(left: Any, right: Any) -> dict[str, dict[str, Any]]:
    diffs: dict[str, dict[str, Any]] = {}
    for f in _MONEY:
        a, b = _dec(_get(left, f)), _dec(_get(right, f))
        if a is None or b is None:
            continue
        if abs(a - b) > TOLERANCE:
            diffs[f] = {"left": str(a), "right": str(b), "difference": str(a - b)}
    for f in _OTHER:
        a, b = _get(left, f), _get(right, f)
        if a is None or b is None:
            continue
        if str(a).strip().upper() != str(b).strip().upper():
            diffs[f] = {"left": str(a), "right": str(b)}
    return diffs


def crosscheck(left: Any, right: Any, kind: CrosscheckKind | str | None = None) -> CrosscheckResult:
    """Compare one invoice with another invoice, or with a list of ledger rows."""
    rows = right if isinstance(right, list) else [right]
    kind = CrosscheckKind(kind) if kind else (CrosscheckKind.PDF_EXCEL if isinstance(right, list) else CrosscheckKind.PDF_PDF)
    key = match_key(left)
    candidates = [r for r in rows if key is not None and match_key(r) == key]
    if not candidates:
        right_ref = _ref(rows[0]) if len(rows) == 1 else {"rows": len(rows)}
        return CrosscheckResult(kind=kind, left_ref=_ref(left), right_ref=right_ref, result=CrosscheckOutcome.NO_MATCH,
                                details={"reason": "no document with the same invoice number and supplier"})
    best = min(candidates, key=lambda r: len(_compare(left, r)))
    diffs = _compare(left, best)
    return CrosscheckResult(kind=kind, left_ref=_ref(left), right_ref=_ref(best),
                            result=CrosscheckOutcome.MISMATCH if diffs else CrosscheckOutcome.MATCH,
                            details={"differences": diffs} if diffs else {})


def crosscheck_batch(kind: CrosscheckKind | str, left_items: Iterable[Any], right_items: Iterable[Any]) -> dict[str, Any]:
    """Match many items at once with a dict index.

    Returns {"results": [CrosscheckResult per left item], "unmatched_right": [refs]}.
    """
    kind = CrosscheckKind(kind)
    index: dict[tuple[str, str], list[Any]] = {}
    rights = list(right_items)
    for r in rights:
        k = match_key(r)
        if k is not None:
            index.setdefault(k, []).append(r)
    used: set[int] = set()
    results: list[CrosscheckResult] = []
    for left in left_items:
        k = match_key(left)
        cands = index.get(k, []) if k else []
        if not cands:
            results.append(CrosscheckResult(kind=kind, left_ref=_ref(left), right_ref={}, result=CrosscheckOutcome.NO_MATCH,
                                            details={"reason": "no document with the same invoice number and supplier"}))
            continue
        best = min(cands, key=lambda r: len(_compare(left, r)))
        used.add(id(best))
        diffs = _compare(left, best)
        results.append(CrosscheckResult(kind=kind, left_ref=_ref(left), right_ref=_ref(best),
                                        result=CrosscheckOutcome.MISMATCH if diffs else CrosscheckOutcome.MATCH,
                                        details={"differences": diffs} if diffs else {}))
    unmatched = [_ref(r) for r in rights if id(r) not in used]
    return {"results": results, "unmatched_right": unmatched}


def crosscheck_issues(result: CrosscheckResult) -> list[IssueModel]:
    if result.result == CrosscheckOutcome.MATCH:
        return []
    other = "spreadsheet" if result.kind == CrosscheckKind.PDF_EXCEL else "other document"
    if result.result == CrosscheckOutcome.NO_MATCH:
        return [IssueModel(code=IssueCode.CROSS_NO_MATCH, severity=IssueSeverity.ERROR, field="invoice_number",
                           message=f"No matching entry was found in the {other}.",
                           details={"kind": result.kind.value if hasattr(result.kind, "value") else result.kind, "right_ref": result.right_ref})]
    code = IssueCode.CROSS_EXCEL_MISMATCH if result.kind == CrosscheckKind.PDF_EXCEL else IssueCode.CROSS_PDF_MISMATCH
    diffs = result.details.get("differences", {})
    fields = ", ".join(diffs) or "some fields"
    return [IssueModel(code=code, severity=IssueSeverity.ERROR, field=next(iter(diffs), None),
                       message=f"The {other} shows different values for: {fields}.",
                       details={"differences": diffs, "right_ref": result.right_ref})]

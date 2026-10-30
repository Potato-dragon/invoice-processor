"""Duplicate-candidate lookups: a Protocol, a DB version and an in-memory one."""
from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

_LEGAL_SUFFIXES = {
    "ltd", "limited", "inc", "incorporated", "llc", "llp", "lp", "plc", "corp", "corporation", "co", "company",
    "gmbh", "ag", "kg", "ug", "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "oy", "ab", "as", "aps", "pty",
    "pvt", "private", "kk", "sl", "sae", "se",
}


def normalize_supplier(name: str | None) -> str:
    """Lowercase, strip accents, punctuation and legal suffixes ('Acme Ltd.' -> 'acme')."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    # Drop dots first so "S.A." becomes "sa" and matches a legal suffix.
    words = re.sub(r"[^a-z0-9 ]+", " ", text.replace(".", "").replace("&", " and ")).split()
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_invoice_number(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


@dataclass(frozen=True)
class ExistingInvoice:
    id: str
    supplier_name: str | None
    invoice_number: str | None
    total: Decimal | None
    invoice_date: str | None


class DuplicateLookup(Protocol):
    def find_candidates(
        self, supplier_name: str | None, invoice_number: str | None, total: Decimal | None, invoice_date: str | None
    ) -> list[ExistingInvoice]: ...


class InMemoryDuplicateLookup:
    """For tests and batch tools: candidates are every stored invoice except one."""

    def __init__(self, invoices: list[ExistingInvoice] | None = None, exclude_id: str | None = None) -> None:
        self._invoices = list(invoices or [])
        self._exclude = exclude_id

    def add(self, inv: ExistingInvoice) -> None:
        self._invoices.append(inv)

    def find_candidates(self, supplier_name, invoice_number, total, invoice_date) -> list[ExistingInvoice]:  # noqa: ANN001
        return [i for i in self._invoices if i.id != self._exclude]


class DbDuplicateLookup:
    """Queries the invoices table using its indexes; never returns the invoice itself.

    Pre-filters in SQL (same invoice number, or same total) and leaves the
    fuzzy supplier comparison to Python. `older_than` / `newer_than` take an
    order key (document created_at, document id, page_start) so an invoice is
    only flagged against invoices received before it.
    """

    def __init__(self, session: Any, exclude_invoice_id: str | uuid.UUID | None = None, *,
                 older_than: tuple | None = None, newer_than: tuple | None = None) -> None:
        self._session = session
        self._exclude = exclude_invoice_id
        self._older_than = older_than
        self._newer_than = newer_than

    def find_candidates(self, supplier_name, invoice_number, total, invoice_date) -> list[ExistingInvoice]:  # noqa: ANN001
        from sqlalchemy import or_, select, tuple_

        from app.models import Document, Invoice

        conds = []
        if invoice_number:
            conds.append(Invoice.invoice_number == invoice_number)
        if total is not None:
            conds.append(Invoice.total == total)
        if not conds:
            return []
        stmt = (select(Invoice.id, Invoice.supplier_name, Invoice.invoice_number, Invoice.total, Invoice.invoice_date)
                .join(Document, Document.id == Invoice.document_id).where(or_(*conds)))
        if self._exclude is not None:
            stmt = stmt.where(Invoice.id != self._exclude)
        order_key = tuple_(Document.created_at, Invoice.document_id, Invoice.page_start)
        if self._older_than is not None:
            stmt = stmt.where(order_key < tuple_(*self._older_than))
        if self._newer_than is not None:
            stmt = stmt.where(order_key > tuple_(*self._newer_than))
        stmt = stmt.limit(200)
        return [
            ExistingInvoice(id=str(r.id), supplier_name=r.supplier_name, invoice_number=r.invoice_number,
                            total=Decimal(r.total) if r.total is not None else None, invoice_date=r.invoice_date)
            for r in self._session.execute(stmt)
        ]


class ContractLookupAdapter:
    """Adapts the contracts.DuplicateLookup model (lists of dicts) to the Protocol."""

    def __init__(self, model: Any) -> None:
        self._rows = list(getattr(model, "exact_matches", [])) + list(getattr(model, "fuzzy_matches", []))

    def find_candidates(self, supplier_name, invoice_number, total, invoice_date) -> list[ExistingInvoice]:  # noqa: ANN001
        out = []
        for r in self._rows:
            t = r.get("total")
            out.append(ExistingInvoice(id=str(r.get("id")), supplier_name=r.get("supplier_name"),
                                       invoice_number=r.get("invoice_number"),
                                       total=Decimal(str(t)) if t is not None else None, invoice_date=r.get("invoice_date")))
        return out

"use client";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { StatusBadge } from "@/components/Badges";
import { api, fmtMoney, InvoiceSummary, Page, qs } from "@/lib/api";

type Result = Page<InvoiceSummary> & { mode: string };

export default function SearchPage() {
  const [f, setF] = useState({ q: "", mode: "hybrid", supplier: "", currency: "", date_from: "", date_to: "", min_total: "", max_total: "", review_status: "" });
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run(e?: FormEvent) {
    e?.preventDefault();
    setLoading(true);
    try {
      setRes(await api.get<Result>(`/search${qs({ ...f, limit: 50 })}`));
      setErr(null);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  return (
    <>
      <h1>Search invoices</h1>
      <p className="sub">Keyword search matches words and numbers exactly; semantic search finds invoices with a similar meaning (e.g. “cloud consulting”); hybrid combines both.</p>
      <form className="panel" onSubmit={run}>
        <div className="row" style={{ marginBottom: 10 }}>
          <input style={{ flex: "1 1 280px" }} placeholder="e.g. INV-2026-D001, freight services, Apex" value={f.q} onChange={set("q")} />
          <select value={f.mode} onChange={set("mode")}>
            <option value="hybrid">Hybrid</option>
            <option value="keyword">Keyword</option>
            <option value="semantic">Semantic</option>
          </select>
          <button className="primary" type="submit" disabled={loading}>{loading ? "Searching…" : "Search"}</button>
        </div>
        <div className="row">
          <input placeholder="Supplier contains" value={f.supplier} onChange={set("supplier")} />
          <input placeholder="Currency (EUR)" value={f.currency} onChange={set("currency")} style={{ width: 120 }} />
          <label className="muted">from <input type="date" value={f.date_from} onChange={set("date_from")} /></label>
          <label className="muted">to <input type="date" value={f.date_to} onChange={set("date_to")} /></label>
          <input placeholder="Min total" value={f.min_total} onChange={set("min_total")} style={{ width: 110 }} />
          <input placeholder="Max total" value={f.max_total} onChange={set("max_total")} style={{ width: 110 }} />
          <select value={f.review_status} onChange={set("review_status")}>
            <option value="">Any review status</option>
            <option value="NEEDS_REVIEW">Needs review</option>
            <option value="AUTO_OK">Auto OK</option>
            <option value="CORRECTED">Corrected</option>
          </select>
        </div>
      </form>
      {err && <div className="error-box">{err}</div>}
      {res && (
        <div className="panel">
          <p className="muted" style={{ marginTop: 0 }}>{res.total} result(s){res.mode !== "filter" && ` · ${res.mode} ranking`}</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Invoice</th><th>Supplier</th><th>Customer</th><th>Date</th><th className="num">Total</th><th>Review</th><th>File</th>{res.mode !== "filter" && <th className="num">Score</th>}</tr></thead>
              <tbody>
                {res.items.map((i) => (
                  <tr key={i.id}>
                    <td><Link href={`/invoices/${i.id}`}>{i.invoice_number ?? "(missing)"}</Link></td>
                    <td>{i.supplier_name ?? "—"}</td>
                    <td>{i.customer_name ?? "—"}</td>
                    <td>{i.invoice_date ?? "—"}</td>
                    <td className="num">{fmtMoney(i.total, i.currency)}</td>
                    <td><StatusBadge status={i.review_status} /></td>
                    <td className="muted"><Link href={`/documents/${i.document_id}`}>{i.filename}</Link></td>
                    {res.mode !== "filter" && <td className="num muted">{i.score ?? ""}</td>}
                  </tr>
                ))}
                {res.items.length === 0 && <tr><td colSpan={8} className="muted">Nothing found.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, InvoiceSummary, Page, qs } from "@/lib/api";
import { Alert, Empty, Icon, Loading, MethodTag, Money, PageHead, Pill } from "@/components/ui";

type Result = Page<InvoiceSummary> & { mode: string };

const MODES = [
  { key: "hybrid", label: "Hybrid", hint: "Combines both rankings (reciprocal-rank fusion). Best default." },
  { key: "keyword", label: "Exact words", hint: "Matches words and numbers as typed: invoice numbers, names, amounts." },
  { key: "semantic", label: "Similar meaning", hint: "Finds invoices about the same thing, even in other words: “cloud consulting” finds “architecture advisory”." },
];
const EXAMPLES = ["freight services", "software licence", "consulting", "office supplies"];
const EMPTY = { q: "", mode: "hybrid", supplier: "", currency: "", date_from: "", date_to: "", min_total: "", max_total: "", review_status: "" };

export default function SearchPage() {
  const router = useRouter();
  const [f, setF] = useState(EMPTY);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showFilters, setShowFilters] = useState(false);

  async function run(next = f, e?: FormEvent) {
    e?.preventDefault();
    setLoading(true);
    try {
      setRes(await api.get<Result>(`/search${qs({ ...next, limit: 50 })}`));
      setErr(null);
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const activeFilters = (["supplier", "currency", "date_from", "date_to", "min_total", "max_total", "review_status"] as const).filter((k) => f[k]).length;
  const maxScore = Math.max(0, ...(res?.items.map((i) => i.score ?? 0) ?? [0]));

  return (
    <>
      <PageHead eyebrow="Search" title="Find any invoice">
        Search by invoice number, supplier, amount or by what the invoice is about. Results come from the full text and a local embedding model, so no AI quota is used.
      </PageHead>

      <form className="card" onSubmit={(e) => run(f, e)}>
        <div className="card-b grid" style={{ gap: 14 }}>
          <div className="row" style={{ gap: 10 }}>
            <label className="searchbox" style={{ flex: "1 1 320px" }}>
              <Icon name="search" size={16} />
              <input id="search-q" aria-label="Search" style={{ padding: "10px 12px 10px 34px", fontSize: "1rem" }} placeholder="INV-2026-0042, Apex Logistics, freight services…" value={f.q} onChange={set("q")} />
            </label>
            <button className="primary" type="submit" disabled={loading} style={{ padding: "10px 18px" }}>{loading ? "Searching…" : "Search"}</button>
          </div>
          <div className="row" style={{ gap: 12 }}>
            <div className="seg" role="radiogroup" aria-label="Search mode">
              {MODES.map((m) => (
                <button type="button" key={m.key} role="radio" aria-checked={f.mode === m.key} className={f.mode === m.key ? "on" : ""} onClick={() => { const n = { ...f, mode: m.key }; setF(n); if (f.q) run(n); }}>{m.label}</button>
              ))}
            </div>
            <span className="small muted" style={{ flex: "1 1 260px" }}>{MODES.find((m) => m.key === f.mode)?.hint}</span>
            <button type="button" className="sm" onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
              Filters{activeFilters ? ` (${activeFilters})` : ""}
            </button>
          </div>
          {!f.q && (
            <div className="row small muted" style={{ gap: 6 }}>
              Try:
              {EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => { const n = { ...f, q: x }; setF(n); run(n); }}>{x}</button>)}
            </div>
          )}
          {showFilters && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12, paddingTop: 12, borderTop: "1px solid var(--line)" }}>
              <label className="field" htmlFor="flt-supplier">Supplier contains<input id="flt-supplier" value={f.supplier} onChange={set("supplier")} /></label>
              <label className="field" htmlFor="flt-currency">Currency<input id="flt-currency" placeholder="EUR" value={f.currency} onChange={set("currency")} /></label>
              <label className="field" htmlFor="flt-from">Date from<input id="flt-from" type="date" value={f.date_from} onChange={set("date_from")} /></label>
              <label className="field" htmlFor="flt-to">Date to<input id="flt-to" type="date" value={f.date_to} onChange={set("date_to")} /></label>
              <label className="field" htmlFor="flt-min">Total at least<input id="flt-min" inputMode="decimal" value={f.min_total} onChange={set("min_total")} /></label>
              <label className="field" htmlFor="flt-max">Total at most<input id="flt-max" inputMode="decimal" value={f.max_total} onChange={set("max_total")} /></label>
              <label className="field" htmlFor="flt-review">Review status
                <select id="flt-review" value={f.review_status} onChange={set("review_status")}>
                  <option value="">Any</option><option value="NEEDS_REVIEW">Needs review</option><option value="AUTO_OK">Auto-approved</option><option value="CORRECTED">Corrected</option>
                </select>
              </label>
              <div className="row" style={{ alignSelf: "end" }}>
                <button type="submit" className="sm primary">Apply</button>
                <button type="button" className="sm ghost" onClick={() => { const n = { ...EMPTY, q: f.q, mode: f.mode }; setF(n); run(n); }}>Clear</button>
              </div>
            </div>
          )}
        </div>
      </form>

      {err && <Alert tone="err" title="Search failed">{err}</Alert>}

      <section className="card">
        <div className="card-h">
          <h2>{res ? (res.mode === "filter" ? "Latest invoices" : "Results") : "Results"}</h2>
          {res && <span className="sub">{res.total} invoice{res.total === 1 ? "" : "s"}{res.mode !== "filter" && ` · ranked by ${MODES.find((m) => m.key === res.mode)?.label.toLowerCase()}`}</span>}
        </div>
        {!res ? <div className="card-b"><Loading /></div> : res.items.length === 0 ? (
          <Empty icon="search" title="Nothing found">Try fewer words, the “Similar meaning” mode, or clear the filters.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Invoice</th><th>Customer</th><th>Date</th><th className="num">Total</th><th>Read by</th><th>Review</th>{res.mode !== "filter" && <th>Relevance</th>}</tr>
              </thead>
              <tbody>
                {res.items.map((i) => (
                  <tr key={i.id} className="click" onClick={() => router.push(`/invoices/${i.id}`)}>
                    <td>
                      <div className="cell-title">
                        <Link href={`/invoices/${i.id}`} onClick={(e) => e.stopPropagation()}><span className="mono">{i.invoice_number ?? "number missing"}</span></Link>
                        <span className="sub truncate">{i.supplier_name ?? "supplier missing"} · {i.filename}</span>
                      </div>
                    </td>
                    <td className="muted"><span className="truncate" style={{ maxWidth: 200 }}>{i.customer_name ?? "—"}</span></td>
                    <td className="num muted">{i.invoice_date ?? "—"}</td>
                    <td className="num"><Money value={i.total} currency={i.currency} /></td>
                    <td><MethodTag method={i.extraction_method} /></td>
                    <td><Pill status={i.review_status} /></td>
                    {res.mode !== "filter" && (
                      <td>
                        <span className="score" title={`score ${i.score}`}>
                          <span className="m"><i style={{ width: `${maxScore ? ((i.score ?? 0) / maxScore) * 100 : 0}%` }} /></span>
                          <span className="mono faint small">{i.score?.toFixed(3)}</span>
                        </span>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

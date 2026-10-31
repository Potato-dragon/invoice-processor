"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Doc, Page } from "@/lib/api";
import { ago, Alert, Empty, Icon, Kpi, PageHead, Pill } from "@/components/ui";

type Ref = { id?: string; invoice_number?: string; supplier_name?: string; sheet_name?: string; row_no?: number; document_id?: string };
type Check = { id?: string; kind: string; left_ref: Ref; right_ref: Ref; result: string; details: { differences?: Record<string, { left: string; right: string }>; reason?: string }; created_at?: string };
type RunResult = { kind: string; summary: Record<string, number>; unmatched_right_count: number; unmatched_right: Ref[]; items: Check[] };

const FIELD: Record<string, string> = { total: "Total", subtotal: "Subtotal", tax: "Tax", invoice_date: "Date", currency: "Currency" };

function Diffs({ c }: { c: Check }) {
  const d = c.details.differences;
  if (d && Object.keys(d).length) {
    return (
      <div className="diff">
        {Object.entries(d).map(([k, v]) => (
          <span key={k} style={{ display: "contents" }}>
            <span className="f">{FIELD[k] ?? k}</span><span className="b">{v.left}</span><span className="a" title="value on the other side">{v.right}</span>
          </span>
        ))}
      </div>
    );
  }
  return <span className="muted small">{c.result === "MATCH" ? "All compared fields agree" : c.details.reason ?? ""}</span>;
}

function Other({ r }: { r: Ref }) {
  // CSV files have no sheet names; the backend uses an internal id there.
  if (r.sheet_name) return <span className="muted small">{/^[0-9a-f]{32}$/.test(r.sheet_name) ? "spreadsheet" : `sheet “${r.sheet_name}”`}, row {r.row_no}</span>;
  if (r.id) return <Link href={`/invoices/${r.id}`} className="mono small">{r.invoice_number ?? "invoice"}</Link>;
  return <span className="faint">—</span>;
}

export default function CrosschecksPage() {
  const [sheets, setSheets] = useState<Doc[]>([]);
  const [sheet, setSheet] = useState("");
  const [kind, setKind] = useState("PDF_EXCEL");
  const [run, setRun] = useState<RunResult | null>(null);
  const [filter, setFilter] = useState("problems");
  const [histFilter, setHistFilter] = useState("MISMATCH");
  const [history, setHistory] = useState<Page<Check> | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const docs = await api.get<Page<Doc>>("/documents?kind=spreadsheet&limit=200");
      setSheets(docs.items.filter((d) => d.status !== "FAILED"));
      setHistory(await api.get<Page<Check>>("/crosschecks?limit=50"));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function start() {
    setBusy(true);
    try {
      const body = kind === "PDF_EXCEL" ? { kind, right_ids: sheet ? [sheet] : [] } : { kind };
      setRun(await api.post<RunResult>("/crosschecks/run", body));
      setFilter("problems");
      setErr(null);
      load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const RANK: Record<string, number> = { MISMATCH: 0, MATCH: 1, NO_MATCH: 2 };
  const hist = (history?.items ?? []).filter((c) => histFilter === "all" || c.result === histFilter).sort((a, b) => (RANK[a.result] ?? 3) - (RANK[b.result] ?? 3));
  const histCount = (k: string) => (history?.items ?? []).filter((c) => c.result === k).length;
  const rows = run ? run.items.filter((c) => filter === "all" || (filter === "problems" ? c.result !== "MATCH" : c.result === filter)) : [];

  return (
    <>
      <PageHead eyebrow="Cross-checks" title="Compare invoices with your records">
        Match PDF invoices against spreadsheet rows (for example an accounts-payable export), or against each other. Pairs are matched on invoice number and supplier; totals, tax, dates and currency are then compared, and every difference becomes an issue on the invoice.
      </PageHead>

      <section className="card">
        <div className="card-b row" style={{ gap: 12 }}>
          <div className="seg" role="radiogroup" aria-label="What to compare">
            <button role="radio" aria-checked={kind === "PDF_EXCEL"} className={kind === "PDF_EXCEL" ? "on" : ""} onClick={() => setKind("PDF_EXCEL")}>PDFs vs spreadsheet</button>
            <button role="radio" aria-checked={kind === "PDF_PDF"} className={kind === "PDF_PDF" ? "on" : ""} onClick={() => setKind("PDF_PDF")}>PDFs vs PDFs</button>
          </div>
          {kind === "PDF_EXCEL" && (
            <select id="cc-sheet" aria-label="Spreadsheet" value={sheet} onChange={(e) => setSheet(e.target.value)}>
              <option value="">All spreadsheets ({sheets.length})</option>
              {sheets.map((s) => <option key={s.id} value={s.id}>{s.filename}</option>)}
            </select>
          )}
          <span className="spacer" />
          <button className="primary" onClick={start} disabled={busy || (kind === "PDF_EXCEL" && sheets.length === 0)}>
            <Icon name="compare" size={15} />{busy ? "Comparing…" : "Run cross-check"}
          </button>
        </div>
        {kind === "PDF_EXCEL" && sheets.length === 0 && (
          <div className="card-f small muted">No spreadsheet uploaded yet. Upload an XLSX, XLS or CSV on the <Link href="/documents">Documents</Link> page first.</div>
        )}
      </section>

      {err && <Alert tone="err" title="Cross-check failed">{err}</Alert>}

      {run && (
        <>
          <div className="kpis">
            <Kpi label="Matched and equal" value={run.summary.MATCH ?? 0} tone="ok" />
            <Kpi label="Matched but different" value={run.summary.MISMATCH ?? 0} tone={run.summary.MISMATCH ? "err" : undefined} detail="become issues on the invoice" />
            <Kpi label="No counterpart" value={run.summary.NO_MATCH ?? 0} tone={run.summary.NO_MATCH ? "warn" : undefined} detail="invoice not in the other source" />
            {run.kind === "PDF_EXCEL" && <Kpi label="Rows without a PDF" value={run.unmatched_right_count} detail="in the spreadsheet only" />}
          </div>

          <section className="card">
            <div className="card-h">
              <h2>Result</h2>
              <span className="spacer" />
              <div className="seg" role="tablist">
                {[["problems", "Differences"], ["MISMATCH", "Mismatch"], ["NO_MATCH", "Not found"], ["MATCH", "Match"], ["all", "All"]].map(([k, l]) => (
                  <button key={k} role="tab" aria-selected={filter === k} className={filter === k ? "on" : ""} onClick={() => setFilter(k)}>{l}</button>
                ))}
              </div>
            </div>
            {rows.length === 0 ? <Empty icon="check" title={filter === "problems" ? "No differences found" : "Nothing in this group"} /> : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Invoice</th><th>Result</th><th>Compared with</th><th>Differences <span className="faint" style={{ textTransform: "none", letterSpacing: 0 }}>(invoice · other)</span></th></tr></thead>
                  <tbody>
                    {rows.slice(0, 300).map((c, n) => (
                      <tr key={n}>
                        <td>
                          <div className="cell-title">
                            {c.left_ref.id ? <Link href={`/invoices/${c.left_ref.id}`} className="mono">{c.left_ref.invoice_number ?? "number missing"}</Link> : <span className="mono">{c.left_ref.invoice_number}</span>}
                            <span className="sub">{c.left_ref.supplier_name}</span>
                          </div>
                        </td>
                        <td><Pill status={c.result} /></td>
                        <td><Other r={c.right_ref} /></td>
                        <td><Diffs c={c} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {run.unmatched_right.length > 0 && (
              <div className="card-f small muted">
                Spreadsheet rows with no PDF: {run.unmatched_right.slice(0, 15).map((r) => `${r.invoice_number ?? "?"} (${r.sheet_name} row ${r.row_no})`).join(", ")}{run.unmatched_right.length > 15 && "…"}
              </div>
            )}
          </section>
        </>
      )}

      <section className="card">
        <div className="card-h">
          <h2>Earlier results</h2>{history && <span className="sub">latest {history.items.length} of {history.total} stored</span>}
          <span className="spacer" />
          <div className="seg" role="tablist">
            {[["MISMATCH", "Mismatch"], ["MATCH", "Match"], ["NO_MATCH", "Not found"], ["all", "All"]].map(([k, l]) => (
              <button key={k} role="tab" aria-selected={histFilter === k} className={histFilter === k ? "on" : ""} onClick={() => setHistFilter(k)}>
                {l} <span className="c">{k === "all" ? history?.items.length ?? 0 : histCount(k)}</span>
              </button>
            ))}
          </div>
        </div>
        {!history || history.items.length === 0 ? <Empty icon="compare" title="No cross-checks run yet">Run one above; results are kept here.</Empty> : hist.length === 0 ? <Empty icon="check" title="Nothing in this group" /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Kind</th><th>Invoice</th><th>Result</th><th>Compared with</th><th>Differences</th></tr></thead>
              <tbody>
                {hist.map((c) => (
                  <tr key={c.id}>
                    <td className="muted small">{c.created_at && ago(c.created_at)}</td>
                    <td><span className="kind">{c.kind === "PDF_EXCEL" ? "pdf · sheet" : "pdf · pdf"}</span></td>
                    <td>{c.left_ref.id ? <Link href={`/invoices/${c.left_ref.id}`} className="mono">{c.left_ref.invoice_number}</Link> : <span className="mono">{c.left_ref.invoice_number}</span>}</td>
                    <td><Pill status={c.result} /></td>
                    <td><Other r={c.right_ref} /></td>
                    <td><Diffs c={c} /></td>
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

"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/Badges";
import { api, Doc, fmtTime, Page } from "@/lib/api";

type Ref = { id?: string; invoice_number?: string; supplier_name?: string; sheet_name?: string; row_no?: number; document_id?: string };
type Check = { id?: string; kind: string; left_ref: Ref; right_ref: Ref; result: string; details: { differences?: Record<string, { left: string; right: string }>; reason?: string }; created_at?: string };
type RunResult = { kind: string; summary: Record<string, number>; unmatched_right_count: number; unmatched_right: Ref[]; items: Check[] };

function Diffs({ c }: { c: Check }) {
  const d = c.details.differences;
  if (d) return <>{Object.entries(d).map(([k, v]) => <div key={k}><b>{k}</b>: {v.left} vs {v.right}</div>)}</>;
  return <span className="muted">{c.details.reason ?? ""}</span>;
}

export default function CrosschecksPage() {
  const [sheets, setSheets] = useState<Doc[]>([]);
  const [sheet, setSheet] = useState("");
  const [kind, setKind] = useState("PDF_EXCEL");
  const [run, setRun] = useState<RunResult | null>(null);
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
      setErr(null);
      load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>Cross-checks</h1>
      <p className="sub">Compare PDF invoices with spreadsheet rows (PDF vs Excel) or with each other (PDF vs PDF). Matching uses the invoice number and supplier; totals, tax, dates and currency are then compared.</p>
      <div className="panel">
        <div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="PDF_EXCEL">PDF vs spreadsheet</option>
            <option value="PDF_PDF">PDF vs PDF (all invoices)</option>
          </select>
          {kind === "PDF_EXCEL" && (
            <select value={sheet} onChange={(e) => setSheet(e.target.value)}>
              <option value="">All spreadsheets</option>
              {sheets.map((s) => <option key={s.id} value={s.id}>{s.filename}</option>)}
            </select>
          )}
          <button className="primary" onClick={start} disabled={busy}>{busy ? "Comparing…" : "Run cross-check"}</button>
        </div>
      </div>
      {err && <div className="error-box">{err}</div>}

      {run && (
        <div className="panel">
          <h2>Result</h2>
          <div className="row" style={{ marginBottom: 10 }}>
            <span className="badge b-ok">{run.summary.MATCH} match</span>
            <span className="badge b-err">{run.summary.MISMATCH} mismatch</span>
            <span className="badge b-warn">{run.summary.NO_MATCH} not in the other file</span>
            {kind === "PDF_EXCEL" && <span className="badge b-info">{run.unmatched_right_count} spreadsheet rows with no PDF</span>}
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Invoice</th><th>Supplier</th><th>Result</th><th>Compared with</th><th>Differences</th></tr></thead>
              <tbody>
                {run.items.filter((c) => c.result !== "MATCH").concat(run.items.filter((c) => c.result === "MATCH")).slice(0, 300).map((c, n) => (
                  <tr key={n}>
                    <td>{c.left_ref.id ? <Link href={`/invoices/${c.left_ref.id}`}>{c.left_ref.invoice_number}</Link> : c.left_ref.invoice_number}</td>
                    <td>{c.left_ref.supplier_name}</td>
                    <td><StatusBadge status={c.result} /></td>
                    <td className="muted">{c.right_ref.sheet_name ? `${c.right_ref.sheet_name} row ${c.right_ref.row_no}` : c.right_ref.invoice_number ?? "—"}</td>
                    <td><Diffs c={c} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {run.unmatched_right.length > 0 && (
            <p className="muted">Rows with no matching PDF: {run.unmatched_right.slice(0, 20).map((r) => `${r.invoice_number ?? "?"} (${r.sheet_name} row ${r.row_no})`).join(", ")}</p>
          )}
        </div>
      )}

      {history && history.items.length > 0 && (
        <div className="panel">
          <h2>Recent results ({history.total})</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>When</th><th>Kind</th><th>Invoice</th><th>Result</th><th>Differences</th></tr></thead>
              <tbody>
                {history.items.map((c) => (
                  <tr key={c.id}><td className="muted">{c.created_at && fmtTime(c.created_at)}</td><td>{c.kind}</td><td>{c.left_ref.invoice_number}</td><td><StatusBadge status={c.result} /></td><td><Diffs c={c} /></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

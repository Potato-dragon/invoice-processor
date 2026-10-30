"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StageProgress, StatusBadge } from "@/components/Badges";
import { api, Doc, fmtMoney, fmtTime, IN_FLIGHT, InvoiceSummary, Page, STAGES } from "@/lib/api";

type Detail = Doc & { mime: string; invoices: InvoiceSummary[]; ledger_row_count: number; page_methods: Record<string, number> };
type Event = { id: string; stage: string; event: string; error_code: string | null; detail: Record<string, unknown>; duration_ms: number | null; created_at: string };
type PageText = { page_no: number; method: string; ocr_confidence: number | null; text: string };
type Ledger = { id: string; sheet_name: string; row_no: number; invoice_number: string | null; invoice_date: string | null; supplier_name: string | null; total: string | null; currency: string | null };

export default function DocumentPage({ params }: { params: { id: string } }) {
  const [doc, setDoc] = useState<Detail | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [pages, setPages] = useState<PageText[]>([]);
  const [pageStart, setPageStart] = useState(1);
  const [ledger, setLedger] = useState<Page<Ledger> | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [from, setFrom] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api.get<Detail>(`/documents/${params.id}`);
      setDoc(d);
      setEvents((await api.get<Page<Event>>(`/documents/${params.id}/events`)).items);
      if (d.kind === "spreadsheet") setLedger(await api.get<Page<Ledger>>(`/documents/${params.id}/ledger?limit=200`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [params.id]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!doc || !IN_FLIGHT.has(doc.status)) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [doc, load]);
  useEffect(() => {
    if (!doc?.page_count) return;
    api.get<Page<PageText>>(`/documents/${params.id}/pages?start=${pageStart}&end=${pageStart + 2}`).then((p) => setPages(p.items)).catch(() => setPages([]));
  }, [doc?.page_count, pageStart, params.id]);

  // The file is fetched through the proxy (which adds the key) and shown from a blob URL.
  useEffect(() => {
    if (!doc || doc.kind === "spreadsheet" || doc.error_code?.startsWith("FILE_")) return;
    let url: string | null = null;
    fetch(api.fileUrl(doc.id)).then(async (r) => {
      if (!r.ok) return;
      url = URL.createObjectURL(await r.blob());
      setPreview(url);
    });
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [doc?.id, doc?.kind, doc?.error_code]);

  async function reprocess() {
    try {
      const r = await api.post<{ reprocess_from: string }>(`/documents/${params.id}/reprocess${from ? `?from=${from}` : ""}`);
      setMsg(`Reprocessing from the ${r.reprocess_from} stage.`);
      load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!doc) return <>{err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>}</>;
  const busy = IN_FLIGHT.has(doc.status);

  return (
    <>
      <p className="muted"><Link href="/">← Documents</Link></p>
      <div className="row" style={{ marginBottom: 8 }}>
        <h1 style={{ margin: 0 }}>{doc.filename}</h1>
        <StatusBadge status={doc.status} />
        <div style={{ width: 140 }}><StageProgress status={doc.status} stage={doc.current_stage} /></div>
      </div>
      <p className="sub">
        {doc.kind} · {(doc.size_bytes / 1024).toFixed(0)} KB · {doc.page_count ?? 0} page(s)
        {Object.keys(doc.page_methods).length > 0 && <> · read by {Object.entries(doc.page_methods).map(([m, n]) => `${m.replace("_", " ")} (${n})`).join(", ")}</>}
        {" "}· uploaded {fmtTime(doc.created_at)}
      </p>
      {err && <div className="error-box">{err}</div>}
      {msg && <div className="ok-box">{msg}</div>}
      {doc.status === "FAILED" && (
        <div className="error-box">
          <b>{doc.error_code}</b> at the {doc.current_stage} stage: {doc.error_message}
        </div>
      )}

      <div className="grid two">
        <div>
          {doc.kind !== "spreadsheet" && (
            <div className="panel">
              <h2>Invoices in this document ({doc.invoices.length})</h2>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Pages</th><th>Number</th><th>Supplier</th><th>Date</th><th className="num">Total</th><th>Review</th></tr></thead>
                  <tbody>
                    {doc.invoices.map((i) => (
                      <tr key={i.id}>
                        <td>{i.page_start === i.page_end ? i.page_start : `${i.page_start}–${i.page_end}`}</td>
                        <td><Link href={`/invoices/${i.id}`}>{i.invoice_number ?? "(missing)"}</Link></td>
                        <td>{i.supplier_name ?? "—"}</td>
                        <td>{i.invoice_date ?? "—"}</td>
                        <td className="num">{fmtMoney(i.total, i.currency)}</td>
                        <td><StatusBadge status={i.review_status} />{i.open_errors ? <span className="muted"> {i.open_errors} error(s)</span> : null}</td>
                      </tr>
                    ))}
                    {doc.invoices.length === 0 && <tr><td colSpan={6} className="muted">{busy ? "Still processing…" : "No invoices found."}</td></tr>}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {ledger && (
            <div className="panel">
              <h2>Spreadsheet rows ({ledger.total})</h2>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Sheet</th><th className="num">Row</th><th>Invoice no.</th><th>Date</th><th>Supplier</th><th className="num">Total</th></tr></thead>
                  <tbody>
                    {ledger.items.map((r) => (
                      <tr key={r.id}><td>{r.sheet_name}</td><td className="num">{r.row_no}</td><td>{r.invoice_number ?? "—"}</td><td>{r.invoice_date ?? "—"}</td><td>{r.supplier_name ?? "—"}</td><td className="num">{fmtMoney(r.total, r.currency)}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="muted" style={{ marginBottom: 0 }}>Compare these rows with PDF invoices on the <Link href="/crosschecks">Cross-checks</Link> page.</p>
            </div>
          )}

          <div className="panel">
            <h2>Processing history</h2>
            <ul className="timeline">
              {events.map((e) => (
                <li key={e.id}>
                  <span className="mono" style={{ width: 62 }}>{e.stage}</span>
                  <StatusBadge status={e.event === "SUCCEEDED" ? "COMPLETED" : e.event === "FAILED" ? "FAILED" : e.event === "RETRIED" ? "NEEDS_REVIEW" : "PARSING"} />
                  <span>{e.event.toLowerCase()}</span>
                  {e.duration_ms !== null && <span className="muted">{e.duration_ms} ms</span>}
                  {e.error_code && <span className="badge b-err">{e.error_code}</span>}
                  {typeof e.detail?.message === "string" && <span className="muted">{e.detail.message as string}</span>}
                  <span className="spacer" />
                  <span className="muted">{fmtTime(e.created_at)}</span>
                </li>
              ))}
            </ul>
            <div className="row" style={{ marginTop: 12 }}>
              <select value={from} onChange={(e) => setFrom(e.target.value)} disabled={busy}>
                <option value="">{doc.status === "FAILED" ? `Retry from failed stage (${doc.current_stage})` : "Re-run all stages"}</option>
                {STAGES.map((s) => <option key={s} value={s}>Re-run from {s}</option>)}
              </select>
              <button className="primary" onClick={reprocess} disabled={busy}>Reprocess</button>
            </div>
          </div>
        </div>

        <div>
          {preview && (
            <div className="panel">
              <h2>Original file</h2>
              {doc.mime === "application/pdf" ? <iframe className="preview" src={preview} title="PDF preview" />
                : doc.mime === "image/tiff" ? <p className="muted">TIFF preview is not supported by browsers. <a href={preview} download={doc.filename}>Download the file</a>.</p>
                  : <img className="preview-img" src={preview} alt={doc.filename} />}
            </div>
          )}
          {pages.length > 0 && (
            <div className="panel">
              <div className="row" style={{ marginBottom: 8 }}>
                <h2 style={{ margin: 0 }}>Extracted text</h2>
                <span className="spacer" />
                <button className="small" disabled={pageStart <= 1} onClick={() => setPageStart(Math.max(1, pageStart - 3))}>‹</button>
                <span className="muted">pages {pageStart}–{Math.min(pageStart + 2, doc.page_count ?? 1)}</span>
                <button className="small" disabled={pageStart + 3 > (doc.page_count ?? 1)} onClick={() => setPageStart(pageStart + 3)}>›</button>
              </div>
              {pages.map((p) => (
                <div key={p.page_no} style={{ marginBottom: 10 }}>
                  <div className="muted" style={{ fontSize: "0.8rem", marginBottom: 4 }}>
                    Page {p.page_no} · {p.method.replace("_", " ")}{p.ocr_confidence !== null && ` · OCR confidence ${Math.round(p.ocr_confidence * 100)}%`}
                  </div>
                  <div className="pagetext">{p.text || "(no text)"}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

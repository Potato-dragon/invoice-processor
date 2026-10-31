"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Doc, DocEvent, IN_FLIGHT, InvoiceSummary, Page, STAGES } from "@/lib/api";
import {
  ago, Alert, bytes, Empty, errorLabel, Icon, Loading, MethodTag, Money, ms, PageHead, Pill, Steps, useFilePreview,
} from "@/components/ui";

type Detail = Doc & { mime: string; invoices: InvoiceSummary[]; ledger_row_count: number; page_methods: Record<string, number> };
type PageText = { page_no: number; method: string; ocr_confidence: number | null; text: string };
type Ledger = { id: string; sheet_name: string; row_no: number; invoice_number: string | null; invoice_date: string | null; supplier_name: string | null; total: string | null; currency: string | null };

const READ_BY: Record<string, string> = { text_layer: "text layer", ocr: "OCR", none: "unreadable" };
const STAGE_NAME: Record<string, string> = { parse: "Read", extract: "Extract", validate: "Check", index: "Index" };

export default function DocumentPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [doc, setDoc] = useState<Detail | null>(null);
  const [events, setEvents] = useState<DocEvent[]>([]);
  const [pageNo, setPageNo] = useState(1);
  const [page, setPage] = useState<PageText | null>(null);
  const [ledger, setLedger] = useState<Page<Ledger> | null>(null);
  const [tab, setTab] = useState<"file" | "text">("file");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [from, setFrom] = useState("");

  const load = useCallback(async () => {
    try {
      const d = await api.get<Detail>(`/documents/${params.id}`);
      setDoc(d);
      setEvents((await api.get<Page<DocEvent>>(`/documents/${params.id}/events`)).items);
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
    api.get<Page<PageText>>(`/documents/${params.id}/pages?start=${pageNo}&end=${pageNo}`).then((p) => setPage(p.items[0] ?? null)).catch(() => setPage(null));
  }, [doc?.page_count, pageNo, params.id]);

  const stored = !!doc && doc.kind !== "spreadsheet" && !(doc.status === "FAILED" && doc.current_stage === "parse" && !doc.page_count);
  const preview = useFilePreview(doc?.id, stored);

  // Duration of the latest successful run of each stage.
  const durations = useMemo(() => {
    const out: Record<string, number> = {};
    for (const e of events) if (e.event === "SUCCEEDED" && e.duration_ms !== null && !e.invoice_id) out[e.stage] = e.duration_ms;
    return out;
  }, [events]);

  async function reprocess() {
    try {
      const r = await api.post<{ reprocess_from: string }>(`/documents/${params.id}/reprocess${from ? `?from=${from}` : ""}`);
      setMsg(`Reprocessing from the ${STAGE_NAME[r.reprocess_from] ?? r.reprocess_from} stage.`);
      load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!doc) return err ? <Alert tone="err" title="Could not load this document">{err}</Alert> : <Loading rows={6} />;
  const busy = IN_FLIGHT.has(doc.status);
  const needReview = doc.invoices.filter((i) => i.review_status === "NEEDS_REVIEW").length;
  const total = Object.values(durations).reduce((a, b) => a + b, 0);

  return (
    <>
      <PageHead
        crumbs={[{ href: "/documents", label: "Documents" }]}
        title={<span style={{ wordBreak: "break-word" }}>{doc.filename}</span>}
        actions={
          <>
            <select id="reprocess-from" aria-label="Reprocess from stage" value={from} onChange={(e) => setFrom(e.target.value)} disabled={busy}>
              <option value="">{doc.status === "FAILED" ? `Retry the failed stage` : "Run all stages again"}</option>
              {STAGES.map((s) => <option key={s} value={s}>Run again from “{STAGE_NAME[s]}”</option>)}
            </select>
            <button onClick={reprocess} disabled={busy}><Icon name="refresh" size={15} />Reprocess</button>
          </>
        }
      />

      {msg && <Alert tone="ok">{msg}</Alert>}
      {err && <Alert tone="err">{err}</Alert>}

      <section className="card">
        <div className="card-b grid" style={{ gap: 16 }}>
          <div className="row" style={{ gap: 12 }}>
            <Pill status={doc.status} />
            <span className="muted small">
              {busy ? `Working on “${STAGE_NAME[doc.current_stage ?? "parse"]}”…` : doc.status === "FAILED" ? `Stopped at “${STAGE_NAME[doc.current_stage ?? "parse"]}”` : `Finished in ${ms(total)}`}
            </span>
            {needReview > 0 && <span className="pill warn">{needReview} invoice{needReview === 1 ? "" : "s"} to review</span>}
          </div>
          <Steps status={doc.status} stage={doc.current_stage} durations={durations} />
          <dl className="facts">
            <div><dt>Type</dt><dd>{doc.mime}</dd></div>
            <div><dt>Size</dt><dd>{bytes(doc.size_bytes)}</dd></div>
            <div><dt>Pages</dt><dd>{doc.page_count ?? "—"}</dd></div>
            <div><dt>Read with</dt><dd>{Object.keys(doc.page_methods).length ? Object.entries(doc.page_methods).map(([m, n]) => `${READ_BY[m] ?? m} (${n} page${n === 1 ? "" : "s"})`).join(", ") : "—"}</dd></div>
            {doc.kind === "spreadsheet" && <div><dt>Ledger rows</dt><dd>{doc.ledger_row_count}</dd></div>}
            <div><dt>Uploaded</dt><dd title={new Date(doc.created_at).toLocaleString()}>{ago(doc.created_at)}</dd></div>
          </dl>
        </div>
      </section>

      {doc.status === "FAILED" && (
        <Alert tone="err" title={`${errorLabel(doc.error_code ?? "")} (${doc.error_code})`}>
          {doc.error_message}. {stored ? "Fix the cause, then reprocess." : "The file was rejected at upload and not stored; upload a fixed copy."}
        </Alert>
      )}

      <div className="grid split">
        <div className="stack">
          {doc.kind !== "spreadsheet" && (
            <section className="card">
              <div className="card-h"><h2>Invoices in this file</h2><span className="sub">{doc.invoices.length} found{doc.invoices.length > 1 && ", split by page"}</span></div>
              {doc.invoices.length === 0 ? <Empty title={busy ? "Still processing…" : "No invoices found"}>{busy ? "They appear here as soon as extraction finishes." : undefined}</Empty> : (
                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Pages</th><th>Invoice</th><th className="num">Total</th><th>Read by</th><th>Review</th></tr></thead>
                    <tbody>
                      {doc.invoices.map((i) => (
                        <tr key={i.id} className="click" onClick={() => router.push(`/invoices/${i.id}`)}>
                          <td className="muted num">{i.page_start === i.page_end ? i.page_start : `${i.page_start}–${i.page_end}`}</td>
                          <td>
                            <div className="cell-title">
                              <Link href={`/invoices/${i.id}`} className="mono" onClick={(e) => e.stopPropagation()}>{i.invoice_number ?? "number missing"}</Link>
                              <span className="sub truncate">{i.supplier_name ?? "supplier missing"}{i.invoice_date && ` · ${i.invoice_date}`}</span>
                            </div>
                          </td>
                          <td className="num"><Money value={i.total} currency={i.currency} /></td>
                          <td><MethodTag method={i.extraction_method} /></td>
                          <td><div className="cell-title"><span><Pill status={i.review_status} /></span>{i.open_errors ? <span className="sub">{i.open_errors} open error{i.open_errors === 1 ? "" : "s"}</span> : null}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {ledger && (
            <section className="card">
              <div className="card-h"><h2>Spreadsheet rows</h2><span className="sub">{ledger.total} rows</span><span className="spacer" /><Link href="/crosschecks" className="small">Compare with PDFs</Link></div>
              <div className="table-wrap" style={{ maxHeight: 520 }}>
                <table>
                  <thead><tr><th>Sheet</th><th className="num">Row</th><th>Invoice no.</th><th>Date</th><th>Supplier</th><th className="num">Total</th></tr></thead>
                  <tbody>
                    {ledger.items.map((r) => (
                      <tr key={r.id}>
                        <td className="muted">{r.sheet_name}</td><td className="num muted">{r.row_no}</td><td className="mono">{r.invoice_number ?? "—"}</td>
                        <td>{r.invoice_date ?? "—"}</td><td>{r.supplier_name ?? "—"}</td><td className="num"><Money value={r.total} currency={r.currency} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          <section className="card">
            <div className="card-h"><h2>Processing history</h2><span className="sub">Every stage logs when it starts, finishes or fails</span></div>
            {events.length === 0 ? <Empty icon="clock" title="No events yet" /> : (
              <ul className="tl">
                {events.map((e) => {
                  const tone = e.event === "SUCCEEDED" ? "ok" : e.event === "FAILED" ? "err" : e.event === "RETRIED" ? "warn" : "run";
                  return (
                    <li key={e.id}>
                      <span className={`dot ${tone}`} />
                      <span className="row" style={{ gap: 8 }}>
                        <b style={{ fontWeight: 500 }}>{STAGE_NAME[e.stage] ?? e.stage}</b>
                        <span className="muted">{e.event.toLowerCase()}</span>
                        {e.duration_ms !== null && <span className="mono faint small">{ms(e.duration_ms)}</span>}
                        {e.error_code && <span className="pill err">{e.error_code}</span>}
                        {typeof e.detail?.message === "string" && <span className="muted small">{e.detail.message as string}</span>}
                        {typeof e.detail?.reason === "string" && <span className="muted small">{e.detail.reason as string}</span>}
                      </span>
                      <span className="when">{new Date(e.created_at).toLocaleTimeString()}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>

        {(stored || page) && (
          <section className="card sticky">
            <div className="card-h">
              <div className="seg" role="tablist">
                {stored && <button role="tab" aria-selected={tab === "file"} className={tab === "file" ? "on" : ""} onClick={() => setTab("file")}>Original</button>}
                <button role="tab" aria-selected={tab === "text" || !stored} className={tab === "text" || !stored ? "on" : ""} onClick={() => setTab("text")}>Text the system read</button>
              </div>
              <span className="spacer" />
              {(tab === "text" || !stored) && doc.page_count ? (
                <span className="row small muted">
                  <button className="sm ghost" aria-label="Previous page" disabled={pageNo <= 1} onClick={() => setPageNo(pageNo - 1)}>‹</button>
                  page {pageNo} of {doc.page_count}
                  <button className="sm ghost" aria-label="Next page" disabled={pageNo >= doc.page_count} onClick={() => setPageNo(pageNo + 1)}>›</button>
                </span>
              ) : null}
            </div>
            {tab === "file" && stored ? (
              <div className="viewer">
                {!preview ? <div className="card-b"><Loading rows={3} /></div>
                  : doc.mime === "application/pdf" ? <iframe src={preview} title="Original PDF" />
                    : doc.mime === "image/tiff" ? <Empty icon="image" title="Browsers cannot show TIFF files"><a href={preview} download={doc.filename}>Download the file</a></Empty>
                      : <img src={preview} alt={`Original of ${doc.filename}`} />}
              </div>
            ) : page ? (
              <>
                <div className="card-b row small muted" style={{ paddingBlock: 10 }}>
                  Read with {READ_BY[page.method] ?? page.method}
                  {page.ocr_confidence !== null && <> · OCR confidence <b style={{ color: page.ocr_confidence < 0.6 ? "var(--err)" : "var(--ink)" }}>{Math.round(page.ocr_confidence * 100)}%</b></>}
                  <span className="faint">· tabs mark table cells</span>
                </div>
                <pre className="pagetext">{page.text || "(no text on this page)"}</pre>
              </>
            ) : <Empty title="No text yet" />}
          </section>
        )}
      </div>
    </>
  );
}

"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { StageProgress, StatusBadge } from "@/components/Badges";
import { api, ApiError, Doc, fmtTime, IN_FLIGHT, Page, qs } from "@/lib/api";

type Stats = {
  documents: { total: number; by_status: Record<string, number>; success_rate: number | null; failure_rate: number | null };
  invoices: { total: number; by_extraction_method: Record<string, number> };
  avg_document_processing_ms: number | null;
};
type UploadResult = { filename: string; status: string; error?: { code: string; message: string }; duplicate_of?: string };

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv";

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Page<Doc> | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const limit = 25;

  const load = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([
        api.get<Page<Doc>>(`/documents${qs({ status, q, limit, offset })}`),
        api.get<Stats>("/stats"),
      ]);
      setDocs(d);
      setStats(s);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [status, q, offset]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while anything is still being processed.
  const busy = docs?.items.some((d) => IN_FLIGHT.has(d.status)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy, load]);

  async function send(files: File[]) {
    if (!files.length) return;
    setUploading(true);
    setResults(null);
    try {
      const out: UploadResult[] = [];
      for (let i = 0; i < files.length; i += 20) out.push(...(await api.upload(files.slice(i, i + 20))));
      setResults(out);
      setOffset(0);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : (e as Error).message);
    } finally {
      setUploading(false);
      if (input.current) input.current.value = "";
    }
  }

  const s = stats?.documents.by_status ?? {};
  const inFlight = Object.entries(s).filter(([k]) => IN_FLIGHT.has(k)).reduce((a, [, v]) => a + v, 0);
  const llm = Object.entries(stats?.invoices.by_extraction_method ?? {}).filter(([k]) => k.startsWith("llm")).reduce((a, [, v]) => a + v, 0);

  return (
    <>
      <h1>Documents</h1>
      <p className="sub">Upload invoices, receipts, scans or spreadsheets. Each file is read, checked and stored in the background.</p>

      {stats && (
        <div className="stats" style={{ marginBottom: 16 }}>
          <div className="stat"><div className="n">{stats.documents.total}</div><div className="l">documents</div></div>
          <div className="stat"><div className="n">{inFlight}</div><div className="l">processing now</div></div>
          <div className="stat"><div className="n">{s.NEEDS_REVIEW ?? 0}</div><div className="l">need review</div></div>
          <div className="stat"><div className="n">{s.FAILED ?? 0}</div><div className="l">failed</div></div>
          <div className="stat"><div className="n">{stats.invoices.total}</div><div className="l">invoices found ({llm} used LLM)</div></div>
          <div className="stat"><div className="n">{stats.avg_document_processing_ms ? `${(stats.avg_document_processing_ms / 1000).toFixed(1)}s` : "—"}</div><div className="l">avg processing time</div></div>
        </div>
      )}

      <div className="panel">
        <div
          className={`drop ${over ? "over" : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}
        >
          {uploading ? "Uploading…" : <>Drop files here or <b>click to choose</b> (PDF, JPG, PNG, TIFF, XLSX, XLS, CSV; several at once)</>}
          <input ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => send(Array.from(e.target.files ?? []))} />
        </div>
        {results && (
          <div style={{ marginTop: 12 }}>
            {results.map((r, i) => (
              <div key={i} className="row" style={{ fontSize: "0.9rem", padding: "3px 0" }}>
                <span className="mono">{r.filename}</span>
                {r.error ? <span className="badge b-err">{r.error.code}</span> : <span className="badge b-ok">accepted</span>}
                <span className="muted">{r.error?.message ?? (r.duplicate_of ? "same file was uploaded before" : "")}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {err && <div className="error-box">{err}</div>}

      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <input placeholder="Filter by file name" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value); }} />
          <select value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value); }}>
            <option value="">All statuses</option>
            <option value="UPLOADED,PARSING,EXTRACTING,VALIDATING,INDEXING">Processing</option>
            <option value="COMPLETED">Completed</option>
            <option value="NEEDS_REVIEW">Needs review</option>
            <option value="FAILED">Failed</option>
          </select>
          <span className="spacer" />
          <button onClick={load}>Refresh</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>File</th><th>Status</th><th>Progress</th><th className="num">Pages</th><th className="num">Invoices</th><th className="num">Open errors</th><th>Uploaded</th></tr>
            </thead>
            <tbody>
              {docs?.items.map((d) => (
                <tr key={d.id}>
                  <td><Link href={`/documents/${d.id}`}>{d.filename}</Link><div className="muted" style={{ fontSize: "0.78rem" }}>{d.kind}</div></td>
                  <td><StatusBadge status={d.status} />{d.error_code && <div className="muted" style={{ fontSize: "0.78rem" }}>{d.error_code}</div>}</td>
                  <td><StageProgress status={d.status} stage={d.current_stage} /></td>
                  <td className="num">{d.page_count ?? "—"}</td>
                  <td className="num">{d.invoice_count ?? 0}</td>
                  <td className="num">{d.open_errors ? <span className="badge b-err">{d.open_errors}</span> : 0}</td>
                  <td className="muted">{fmtTime(d.created_at)}</td>
                </tr>
              ))}
              {docs && docs.items.length === 0 && <tr><td colSpan={7} className="muted">No documents yet.</td></tr>}
            </tbody>
          </table>
        </div>
        {docs && docs.total > limit && (
          <div className="row" style={{ marginTop: 10 }}>
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <span className="muted">{offset + 1}–{Math.min(offset + limit, docs.total)} of {docs.total}</span>
            <button disabled={offset + limit >= docs.total} onClick={() => setOffset(offset + limit)}>Next</button>
          </div>
        )}
      </div>
    </>
  );
}

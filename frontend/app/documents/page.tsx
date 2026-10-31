"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, Doc, IN_FLIGHT, Page, qs, Stats } from "@/lib/api";
import { ago, Alert, bytes, Dropzone, Empty, errorLabel, Icon, KindIcon, Loading, PageHead, Pill, Steps } from "@/components/ui";

const FILTERS: { key: string; label: string; status: string; count: (b: Record<string, number>) => number }[] = [
  { key: "all", label: "All", status: "", count: (b) => Object.values(b).reduce((a, v) => a + v, 0) },
  { key: "review", label: "Needs review", status: "NEEDS_REVIEW", count: (b) => b.NEEDS_REVIEW ?? 0 },
  { key: "done", label: "Completed", status: "COMPLETED", count: (b) => b.COMPLETED ?? 0 },
  { key: "busy", label: "Processing", status: "UPLOADED,PARSING,EXTRACTING,VALIDATING,INDEXING", count: (b) => Object.entries(b).filter(([k]) => IN_FLIGHT.has(k)).reduce((a, [, v]) => a + v, 0) },
  { key: "failed", label: "Failed", status: "FAILED", count: (b) => b.FAILED ?? 0 },
];

export default function DocumentsPage({ searchParams }: { searchParams: { status?: string } }) {
  const router = useRouter();
  const [docs, setDocs] = useState<Page<Doc> | null>(null);
  const [by, setBy] = useState<Record<string, number>>({});
  const [status, setStatus] = useState(searchParams.status ?? "");
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const limit = 25;

  const load = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([api.get<Page<Doc>>(`/documents${qs({ status, kind, q, limit, offset })}`), api.get<Stats>("/stats")]);
      setDocs(d);
      setBy(s.documents.by_status);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [status, kind, q, offset]);
  useEffect(() => { load(); }, [load]);

  const busy = docs?.items.some((d) => IN_FLIGHT.has(d.status)) ?? false;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [busy, load]);

  return (
    <>
      <PageHead eyebrow="Documents" title="Uploaded files" actions={<button onClick={load}><Icon name="refresh" size={15} />Refresh</button>}>
        One row per file. A PDF can hold many invoices; a spreadsheet becomes ledger rows you can cross-check against PDFs.
      </PageHead>

      <div className="card card-b"><Dropzone compact onDone={() => { setOffset(0); load(); }} /></div>
      {err && <Alert tone="err" title="Could not load documents">{err}</Alert>}

      <section className="card">
        <div className="card-h">
          <div className="seg" role="tablist" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.key} role="tab" aria-selected={status === f.status} className={status === f.status ? "on" : ""} onClick={() => { setOffset(0); setStatus(f.status); }}>
                {f.label} <span className="c">{f.count(by)}</span>
              </button>
            ))}
          </div>
          <span className="spacer" />
          <select id="doc-kind" aria-label="File type" value={kind} onChange={(e) => { setOffset(0); setKind(e.target.value); }}>
            <option value="">All file types</option>
            <option value="pdf">PDF</option>
            <option value="image">Scans and images</option>
            <option value="spreadsheet">Spreadsheets</option>
          </select>
          <label className="searchbox">
            <Icon name="search" size={15} />
            <input id="doc-q" placeholder="Filter by file name" value={q} onChange={(e) => { setOffset(0); setQ(e.target.value); }} />
          </label>
        </div>
        {!docs ? <div className="card-b"><Loading /></div> : docs.items.length === 0 ? (
          <Empty title={q || status || kind ? "No files match these filters" : "No documents yet"}>{q || status || kind ? "Try another filter." : "Upload a file above to get started."}</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>File</th><th>Pipeline</th><th>Status</th><th className="num">Pages</th><th className="num">Invoices</th><th className="num">Open errors</th><th>Uploaded</th></tr>
              </thead>
              <tbody>
                {docs.items.map((d) => (
                  <tr key={d.id} className="click" onClick={() => router.push(`/documents/${d.id}`)}>
                    <td>
                      <div className="row" style={{ flexWrap: "nowrap", gap: 10 }}>
                        <span className="muted"><KindIcon kind={d.kind} /></span>
                        <div className="cell-title">
                          <Link href={`/documents/${d.id}`} className="truncate" onClick={(e) => e.stopPropagation()}>{d.filename}</Link>
                          <span className="sub">{d.kind} · {bytes(d.size_bytes)}</span>
                        </div>
                      </div>
                    </td>
                    <td><Steps status={d.status} stage={d.current_stage} mini /></td>
                    <td>
                      <div className="cell-title"><span><Pill status={d.status} /></span>{d.error_code && <span className="sub">{errorLabel(d.error_code)}</span>}</div>
                    </td>
                    <td className="num">{d.page_count ?? "—"}</td>
                    <td className="num">{d.invoice_count || <span className="faint">0</span>}</td>
                    <td className="num">{d.open_errors ? <span className="pill err">{d.open_errors}</span> : <span className="faint">0</span>}</td>
                    <td className="muted small" title={new Date(d.created_at).toLocaleString()}>{ago(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {docs && docs.total > limit && (
          <div className="card-f pager">
            <span>{offset + 1}–{Math.min(offset + limit, docs.total)} of {docs.total}</span>
            <button className="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
            <button className="sm" disabled={offset + limit >= docs.total} onClick={() => setOffset(offset + limit)}>Next</button>
          </div>
        )}
      </section>
    </>
  );
}

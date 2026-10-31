"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, Doc, IN_FLIGHT, Page, Stats } from "@/lib/api";
import {
  ago, Alert, BarList, Dropzone, Empty, errorLabel, Icon, issueLabel, KindIcon, Kpi, Loading, METHOD, ms, PageHead, pct, Pill, StackBar, Steps,
} from "@/components/ui";

const STAGE_ORDER = ["parse", "extract", "validate", "index"];
const STAGE_NAME: Record<string, string> = { parse: "Read", extract: "Extract", validate: "Check", index: "Index" };

export default function Overview() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Doc[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([api.get<Stats>("/stats"), api.get<Page<Doc>>("/documents?limit=7")]);
      setStats(s);
      setRecent(d.items);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const by = stats?.documents.by_status ?? {};
  const busy = Object.entries(by).filter(([k]) => IN_FLIGHT.has(k)).reduce((a, [, v]) => a + v, 0);
  useEffect(() => {
    if (!busy && !recent.some((d) => IN_FLIGHT.has(d.status))) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [busy, recent, load]);

  const methods = stats?.invoices.by_extraction_method ?? {};
  const invTotal = Object.values(methods).reduce((a, b) => a + b, 0);
  const aiCount = Object.entries(methods).filter(([k]) => k.startsWith("llm")).reduce((a, [, v]) => a + v, 0);
  const review = stats?.invoices.by_review_status ?? {};
  const kinds = stats?.documents.by_kind ?? {};
  const stageMax = Math.max(1, ...Object.values(stats?.stages ?? {}).map((s) => s.max_ms ?? s.avg_ms));
  // A log scale keeps a 90 s outlier from flattening the typical 0.1 s bars.
  const scale = (v: number) => Math.log10(1 + v) / Math.log10(1 + stageMax);

  return (
    <>
      <PageHead
        eyebrow="Overview"
        title="Invoice processing at a glance"
        actions={<Link href="/documents" className="btn">All documents <Icon name="arrow" size={15} /></Link>}
      >
        Every upload is read, its fields extracted, the numbers checked and the result indexed for search. Anything the checks are unsure of waits in the review queue.
      </PageHead>

      <div className="card card-b"><Dropzone onDone={load} /></div>
      {err && <Alert tone="err" title="Could not load the dashboard">{err}. Is the API running?</Alert>}

      {!stats ? <Loading rows={5} /> : (
        <>
          <div className="kpis">
            <Kpi label="Documents" value={stats.documents.total}
              detail={[kinds.pdf && `${kinds.pdf} PDF`, kinds.image && `${kinds.image} scans`, kinds.spreadsheet && `${kinds.spreadsheet} sheets`].filter(Boolean).join(" · ") || "none yet"} href="/documents" />
            <Kpi label="Processed successfully" value={pct(stats.documents.success_rate)} tone="ok" detail={`${(by.COMPLETED ?? 0) + (by.NEEDS_REVIEW ?? 0)} of ${stats.documents.total} files`} />
            <Kpi label="Invoices to review" value={review.NEEDS_REVIEW ?? 0} tone={review.NEEDS_REVIEW ? "warn" : undefined} detail={`of ${stats.invoices.total} invoices found`} href="/review" />
            <Kpi label="Failed files" value={by.FAILED ?? 0} tone={by.FAILED ? "err" : undefined} detail="rejected or unreadable" href="/documents?status=FAILED" />
            <Kpi label="Read without AI" value={pct(invTotal ? 1 - aiCount / invTotal : null)} detail={`Gemma helped on ${aiCount} invoice${aiCount === 1 ? "" : "s"}`} />
            <Kpi label="Avg. time per file" value={ms(stats.avg_document_processing_ms)} detail={busy ? `${busy} processing now` : "all four stages"} tone={busy ? "run" : undefined} />
          </div>

          <div className="grid split-wide">
            <div className="stack">
              <section className="card">
                <div className="card-h"><h2>Document status</h2><span className="sub">Where every uploaded file stands</span></div>
                <div className="card-b">
                  <StackBar segments={[
                    { label: "Completed", value: by.COMPLETED ?? 0, color: "var(--ok)" },
                    { label: "Needs review", value: by.NEEDS_REVIEW ?? 0, color: "var(--warn)" },
                    { label: "Processing", value: busy, color: "var(--run)" },
                    { label: "Failed", value: by.FAILED ?? 0, color: "var(--err)" },
                  ]} />
                </div>
              </section>

              <section className="card">
                <div className="card-h"><h2>Where the time goes</h2><span className="sub">Average per run, with the slowest run marked (log scale)</span></div>
                <div className="card-b timing">
                  {STAGE_ORDER.filter((s) => stats.stages[s]).map((s) => {
                    const st = stats.stages[s];
                    return (
                      <div key={s} className="it">
                        <span>{STAGE_NAME[s]}</span>
                        <span className="track" title={`average ${ms(st.avg_ms)}, slowest ${ms(st.max_ms)}, ${st.runs} runs`}>
                          <span className="avg" style={{ width: `${Math.max(1.5, scale(st.avg_ms) * 100)}%` }} />
                          {st.max_ms !== null && <span className="max" style={{ left: `calc(${scale(st.max_ms) * 100}% - 1px)` }} />}
                        </span>
                        <span className="v">{ms(st.avg_ms)}</span>
                      </div>
                    );
                  })}
                  {Object.keys(stats.stages).length === 0 && <Empty icon="clock" title="No runs yet" />}
                  <p className="small muted" style={{ margin: 0 }}>
                    Extraction is the slow step only when Gemma is called; rules-only invoices finish in well under a second.
                  </p>
                </div>
              </section>

              <section className="card">
                <div className="card-h"><h2>Recent uploads</h2><span className="spacer" /><Link href="/documents" className="small">View all</Link></div>
                <div className="card-b flush table-wrap">
                  {recent.length === 0 ? <Empty title="Nothing uploaded yet">Drop a PDF, scan or spreadsheet above to start.</Empty> : (
                    <table>
                      <tbody>
                        {recent.map((d) => (
                          <tr key={d.id} className="click" onClick={() => router.push(`/documents/${d.id}`)}>
                            <td style={{ width: 28 }} className="muted"><KindIcon kind={d.kind} /></td>
                            <td><div className="cell-title"><Link href={`/documents/${d.id}`} className="truncate">{d.filename}</Link><span className="sub">{ago(d.created_at)}</span></div></td>
                            <td><Steps status={d.status} stage={d.current_stage} mini /></td>
                            <td><Pill status={d.status} /></td>
                            <td className="num muted small">{d.invoice_count ? `${d.invoice_count} invoice${d.invoice_count === 1 ? "" : "s"}` : d.error_code ? errorLabel(d.error_code) : ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              </section>
            </div>

            <div className="stack">
              <section className="card">
                <div className="card-h"><h2>How fields were read</h2></div>
                <div className="card-b grid" style={{ gap: 12 }}>
                  <StackBar segments={["rules", "llm_primary", "llm_fallback", "llm_vision", "manual"].map((m) => ({
                    label: METHOD[m][0], value: methods[m] ?? 0,
                    color: m === "rules" ? "var(--accent)" : m === "manual" ? "var(--run)" : m === "llm_vision" ? "var(--warn)" : "var(--llm)",
                  }))} />
                  <p className="small muted" style={{ margin: 0 }}>
                    The rules engine reads every invoice first. Gemma is asked only for fields it could not find or was unsure of, and its answers must be found in the document text.
                  </p>
                </div>
              </section>

              <section className="card">
                <div className="card-h"><h2>Most common issues</h2><span className="spacer" /><Link href="/review" className="small">Review queue</Link></div>
                <div className="card-b">
                  {Object.keys(stats.issues_by_code).length === 0 ? <Empty icon="check" title="No issues found" /> : (
                    <BarList
                      color="var(--warn)"
                      onPick={(code) => router.push(`/review?code=${code}`)}
                      items={Object.entries(stats.issues_by_code).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, v]) => ({ key: k, label: issueLabel(k), value: v }))}
                    />
                  )}
                </div>
              </section>

              <section className="card">
                <div className="card-h"><h2>Why files failed</h2></div>
                <div className="card-b">
                  {Object.keys(stats.documents.by_error_code).length === 0 ? <Empty icon="check" title="No failures" /> : (
                    <BarList
                      color="var(--err)"
                      items={Object.entries(stats.documents.by_error_code).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ key: k, label: errorLabel(k), value: v }))}
                    />
                  )}
                </div>
              </section>
            </div>
          </div>
        </>
      )}
    </>
  );
}

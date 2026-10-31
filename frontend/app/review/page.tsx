"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, InvoiceSummary, Issue, Page, qs } from "@/lib/api";
import { ago, Alert, Empty, Icon, issueLabel, Loading, MethodTag, Money, PageHead } from "@/components/ui";

const SEVERITIES = [
  { key: "error", label: "Blocking" },
  { key: "warning", label: "Warnings" },
  { key: "", label: "Everything" },
];

export default function ReviewPage({ searchParams }: { searchParams: { code?: string } }) {
  const [severity, setSeverity] = useState("error");
  const [code, setCode] = useState(searchParams.code ?? "");
  const [showChecked, setShowChecked] = useState(false);
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [invoices, setInvoices] = useState<Map<string, InvoiceSummary>>(new Map());
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [is, inv] = await Promise.all([
        api.get<Page<Issue>>(`/issues${qs({ severity, resolved: showChecked ? undefined : "false", limit: 1000 })}`),
        api.get<Page<InvoiceSummary>>("/search?limit=200"),
      ]);
      setIssues(is.items);
      setInvoices(new Map(inv.items.map((i) => [i.id, i])));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [severity, showChecked]);
  useEffect(() => { load(); }, [load]);

  const codes = useMemo(() => {
    const m = new Map<string, number>();
    issues?.forEach((i) => m.set(i.code, (m.get(i.code) ?? 0) + 1));
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [issues]);

  // One entry per invoice, worst first.
  const groups = useMemo(() => {
    const shown = (issues ?? []).filter((i) => !code || i.code === code);
    const m = new Map<string, Issue[]>();
    for (const i of shown) {
      const key = i.invoice_id ?? `doc:${i.document_id}`;
      m.set(key, [...(m.get(key) ?? []), i]);
    }
    return Array.from(m.entries()).sort((a, b) =>
      b[1].filter((i) => i.severity === "error").length - a[1].filter((i) => i.severity === "error").length || b[1].length - a[1].length);
  }, [issues, code]);

  async function check(i: Issue) {
    try {
      await api.post(`/issues/${i.id}/resolve`, { resolved: true });
      load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <>
      <PageHead eyebrow="Review queue" title="Invoices waiting for a person">
        The checks flag missing fields, totals that don’t add up, duplicates and values read from poor scans. Open an invoice to compare it with the original and fix it; corrected invoices are checked again automatically.
      </PageHead>
      {err && <Alert tone="err" title="Could not load the queue">{err}</Alert>}

      <section className="card">
        <div className="card-h">
          <div className="seg" role="tablist" aria-label="Severity">
            {SEVERITIES.map((s) => (
              <button key={s.key} role="tab" aria-selected={severity === s.key} className={severity === s.key ? "on" : ""} onClick={() => setSeverity(s.key)}>{s.label}</button>
            ))}
          </div>
          <label className="row small muted" htmlFor="show-checked" style={{ cursor: "pointer" }}>
            <input id="show-checked" type="checkbox" checked={showChecked} onChange={(e) => setShowChecked(e.target.checked)} /> include checked
          </label>
          <span className="spacer" />
          <span className="muted small">{groups.length} item{groups.length === 1 ? "" : "s"} · {groups.reduce((a, [, v]) => a + v.length, 0)} issues</span>
        </div>
        {codes.length > 0 && (
          <div className="card-b" style={{ paddingBlock: 12, borderBottom: "1px solid var(--line)" }}>
            <div className="chips">
              <button className={`chip ${code === "" ? "on" : ""}`} onClick={() => setCode("")}>All types <span className="c">{issues?.length ?? 0}</span></button>
              {codes.map(([c, n]) => (
                <button key={c} className={`chip ${code === c ? "on" : ""}`} onClick={() => setCode(code === c ? "" : c)} title={c}>{issueLabel(c)} <span className="c">{n}</span></button>
              ))}
            </div>
          </div>
        )}

        {!issues ? <div className="card-b"><Loading /></div> : groups.length === 0 ? (
          <Empty icon="check" title="Nothing to review">{severity === "error" ? "No blocking issues. Switch to Warnings to see softer notes." : "No issues match this filter."}</Empty>
        ) : (
          <div>
            {groups.map(([key, list]) => {
              const inv = key.startsWith("doc:") ? undefined : invoices.get(key);
              const errors = list.filter((i) => i.severity === "error" && !i.resolved).length;
              const worst = errors ? "error" : list.some((i) => i.severity === "warning") ? "warning" : "info";
              const href = inv ? `/invoices/${inv.id}` : key.startsWith("doc:") ? `/documents/${key.slice(4)}` : `/invoices/${key}`;
              return (
                <div key={key} className={`issue ${worst}`} style={{ paddingBlock: 14 }}>
                  <span className="stripe" />
                  <div className="grid" style={{ gap: 8 }}>
                    <div className="top" style={{ gap: 12 }}>
                      <div className="cell-title" style={{ minWidth: 0 }}>
                        <Link href={href} style={{ fontWeight: 600 }}>
                          {inv ? <><span className="mono">{inv.invoice_number ?? "number missing"}</span> · {inv.supplier_name ?? "supplier missing"}</> : "Document-level issue"}
                        </Link>
                        {inv && <span className="sub">{inv.filename} · {inv.invoice_date ?? "no date"}</span>}
                      </div>
                      <span className="spacer" />
                      {inv && <MethodTag method={inv.extraction_method} />}
                      {inv && <Money value={inv.total} currency={inv.currency} />}
                      <Link href={href} className="btn sm primary">Review <Icon name="arrow" size={13} /></Link>
                    </div>
                    <div className="grid" style={{ gap: 6 }}>
                      {list.map((i) => (
                        <div key={i.id} className={`fnote ${i.severity}`} style={{ alignItems: "center", opacity: i.resolved ? 0.55 : 1 }}>
                          <Icon name={i.severity === "error" ? "alert" : "info"} size={13} />
                          <b style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{issueLabel(i.code)}</b>
                          <span className="muted" style={{ minWidth: 0 }}>{i.message}</span>
                          <span className="spacer" />
                          <span className="faint small" style={{ whiteSpace: "nowrap" }}>{ago(i.created_at)}</span>
                          {i.severity === "error" && !i.resolved && (i.code.startsWith("DUPLICATE") || i.code === "LOW_CONFIDENCE") && (
                            <button className="sm ghost" onClick={() => check(i)} title="Mark as checked without opening the invoice">Mark checked</button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}

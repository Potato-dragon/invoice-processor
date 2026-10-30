"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/Badges";
import { api, fmtTime, Issue, Page, qs } from "@/lib/api";

export default function ReviewPage() {
  const [severity, setSeverity] = useState("error");
  const [code, setCode] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const [issues, setIssues] = useState<Page<Issue> | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setIssues(await api.get<Page<Issue>>(`/issues${qs({ severity, code, resolved: showResolved ? undefined : "false", limit: 200 })}`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [severity, code, showResolved]);
  useEffect(() => { load(); }, [load]);

  const codes = Array.from(new Set(issues?.items.map((i) => i.code) ?? [])).sort();

  return (
    <>
      <h1>Review queue</h1>
      <p className="sub">Problems found by the checks. Open an invoice to correct values; corrected invoices are checked again automatically.</p>
      <div className="panel">
        <div className="row" style={{ marginBottom: 12 }}>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="error">Errors (block approval)</option>
            <option value="warning">Warnings</option>
            <option value="info">Info</option>
            <option value="">All severities</option>
          </select>
          <select value={code} onChange={(e) => setCode(e.target.value)}>
            <option value="">All issue types</option>
            {codes.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <label className="row muted"><input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} /> include checked</label>
          <span className="spacer" />
          <span className="muted">{issues?.total ?? 0} issue(s)</span>
        </div>
        {err && <div className="error-box">{err}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Severity</th><th>Type</th><th>What is wrong</th><th>Field</th><th>Invoice</th><th>Found</th></tr></thead>
            <tbody>
              {issues?.items.map((i) => (
                <tr key={i.id} style={i.resolved ? { opacity: 0.55 } : undefined}>
                  <td><StatusBadge status={i.severity} /></td>
                  <td className="mono">{i.code}</td>
                  <td>{i.message}</td>
                  <td className="muted">{i.field ?? "—"}</td>
                  <td>{i.invoice_id ? <Link href={`/invoices/${i.invoice_id}`}>Open</Link> : <Link href={`/documents/${i.document_id}`}>Document</Link>}</td>
                  <td className="muted">{fmtTime(i.created_at)}</td>
                </tr>
              ))}
              {issues && issues.items.length === 0 && <tr><td colSpan={6} className="muted">Nothing to review.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

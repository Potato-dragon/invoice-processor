"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Confidence, StatusBadge } from "@/components/Badges";
import { api, ApiError, Field, fmtTime, InvoiceDetail, Issue } from "@/lib/api";

const FIELDS: [string, string][] = [
  ["invoice_number", "Invoice number"], ["invoice_date", "Invoice date"], ["supplier_name", "Supplier"],
  ["customer_name", "Customer"], ["subtotal", "Subtotal"], ["tax", "Tax"], ["total", "Total"], ["currency", "Currency"],
];

export default function InvoicePage({ params }: { params: { id: string } }) {
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setInv(await api.get<InvoiceDetail>(`/invoices/${params.id}`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [params.id]);
  useEffect(() => { load(); }, [load]);

  const field = (name: string): Field => (inv?.extraction?.[name] as Field) ?? { value: null, confidence: 0, evidence: null, page: null };
  const changed = Object.entries(draft).filter(([k, v]) => v !== (field(k).value ?? ""));

  async function save() {
    if (!changed.length) return;
    setSaving(true);
    try {
      const body = Object.fromEntries(changed.map(([k, v]) => [k, v.trim() === "" ? null : v.trim()]));
      setInv(await api.patch<InvoiceDetail>(`/invoices/${params.id}`, body));
      setDraft({});
      setMsg("Saved. Checks were run again on the corrected values.");
      setErr(null);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function resolve(issue: Issue, resolved: boolean) {
    try {
      await api.post(`/issues/${issue.id}/resolve`, { resolved });
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!inv) return <>{err ? <div className="error-box">{err}</div> : <p className="muted">Loading…</p>}</>;
  const issuesByField = new Map<string, Issue[]>();
  inv.issues.forEach((i) => { if (i.field) issuesByField.set(i.field, [...(issuesByField.get(i.field) ?? []), i]); });
  const openErrors = inv.issues.filter((i) => i.severity === "error" && !i.resolved).length;

  return (
    <>
      <p className="muted">
        <Link href="/">Documents</Link> / {inv.document && <Link href={`/documents/${inv.document.id}`}>{inv.document.filename}</Link>}
      </p>
      <div className="row" style={{ marginBottom: 8 }}>
        <h1 style={{ margin: 0 }}>Invoice {inv.invoice_number ?? "(number missing)"}</h1>
        <StatusBadge status={inv.review_status} />
      </div>
      <p className="sub">
        Pages {inv.page_start}–{inv.page_end} · read by <b>{inv.extraction_method ?? "—"}</b>
        {openErrors > 0 ? <> · <span style={{ color: "var(--err)" }}>{openErrors} open error(s)</span></> : " · no open errors"}
      </p>
      {err && <div className="error-box">{err}</div>}
      {msg && <div className="ok-box">{msg}</div>}

      <div className="grid two">
        <div className="panel">
          <div className="row" style={{ marginBottom: 8 }}>
            <h2 style={{ margin: 0 }}>Extracted fields</h2>
            <span className="spacer" />
            <button onClick={() => setDraft({})} disabled={!changed.length}>Undo edits</button>
            <button className="primary" onClick={save} disabled={!changed.length || saving}>{saving ? "Saving…" : `Save ${changed.length || ""} correction${changed.length === 1 ? "" : "s"}`}</button>
          </div>
          <table>
            <tbody>
              {FIELDS.map(([name, label]) => {
                const f = field(name);
                const fieldIssues = issuesByField.get(name) ?? [];
                return (
                  <tr key={name} className="field-row">
                    <td>{label}</td>
                    <td>
                      <input
                        value={draft[name] ?? f.value ?? ""}
                        placeholder="(not found)"
                        onChange={(e) => setDraft({ ...draft, [name]: e.target.value })}
                        style={fieldIssues.some((i) => i.severity === "error" && !i.resolved) ? { borderColor: "var(--err)" } : undefined}
                      />
                      {f.evidence && <div className="evidence">“{f.evidence}”{f.page ? ` (page ${f.page})` : ""}</div>}
                      {fieldIssues.filter((i) => !i.resolved).map((i) => <div key={i.id} className="evidence" style={{ color: i.severity === "error" ? "var(--err)" : "var(--warn)", fontStyle: "normal" }}>{i.message}</div>)}
                    </td>
                    <td style={{ width: 52 }}>{f.value !== null && <Confidence value={f.confidence} />}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 0 }}>
            Money as plain numbers (e.g. 1234.50), dates as YYYY-MM-DD, currency as a 3-letter code. Empty a field to mark it missing.
          </p>
        </div>

        <div>
          <div className="panel">
            <h2>Issues ({inv.issues.length})</h2>
            {inv.issues.length === 0 && <p className="muted">No problems found.</p>}
            {inv.issues.map((i) => (
              <div key={i.id} className={`issue ${i.severity} ${i.resolved ? "resolved" : ""}`}>
                <div className="row">
                  <StatusBadge status={i.severity} />
                  <b className="mono">{i.code}</b>
                  {i.field && <span className="muted">{i.field}</span>}
                  <span className="spacer" />
                  {i.severity === "error" && (
                    <button className="small" onClick={() => resolve(i, !i.resolved)}>{i.resolved ? "Reopen" : "Mark checked"}</button>
                  )}
                </div>
                <div style={{ marginTop: 4 }}>{i.message}</div>
              </div>
            ))}
            {inv.extraction?.notes && inv.extraction.notes.length > 0 && (
              <p className="muted" style={{ fontSize: "0.8rem" }}>Extraction notes: {inv.extraction.notes.join(", ")}</p>
            )}
          </div>

          <div className="panel">
            <h2>Line items ({inv.line_items.length})</h2>
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Description</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Amount</th></tr></thead>
                <tbody>
                  {inv.line_items.map((li) => (
                    <tr key={li.line_no}><td>{li.line_no}</td><td>{li.description ?? "—"}</td><td className="num">{li.quantity ?? "—"}</td><td className="num">{li.unit_price ?? "—"}</td><td className="num">{li.amount ?? "—"}</td></tr>
                  ))}
                  {inv.line_items.length === 0 && <tr><td colSpan={5} className="muted">No line items read.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>

          {inv.corrections.length > 0 && (
            <div className="panel">
              <h2>Correction history</h2>
              <ul className="timeline">
                {inv.corrections.map((c, n) => (
                  <li key={n}><b>{c.field}</b><span className="muted">{c.old_value ?? "(empty)"}</span>→<span>{c.new_value ?? "(empty)"}</span><span className="spacer" /><span className="muted">{fmtTime(c.created_at)}</span></li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

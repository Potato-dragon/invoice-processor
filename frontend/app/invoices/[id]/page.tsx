"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError, Field, InvoiceDetail, Issue } from "@/lib/api";
import { ago, Alert, Conf, Empty, Icon, issueLabel, Loading, MethodTag, Money, PageHead, Pill, useFilePreview } from "@/components/ui";

const FIELDS: { name: string; label: string; required?: boolean; hint: string }[] = [
  { name: "invoice_number", label: "Invoice number", required: true, hint: "as printed" },
  { name: "invoice_date", label: "Invoice date", required: true, hint: "YYYY-MM-DD" },
  { name: "supplier_name", label: "Supplier", required: true, hint: "who sent the invoice" },
  { name: "customer_name", label: "Customer", hint: "who is billed" },
  { name: "subtotal", label: "Subtotal", hint: "e.g. 1234.50" },
  { name: "tax", label: "Tax", hint: "e.g. 259.25" },
  { name: "total", label: "Total", required: true, hint: "e.g. 1493.75" },
  { name: "currency", label: "Currency", hint: "3-letter code, e.g. EUR" },
];
const TOL = 0.02;

function num(v: string | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

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

  const preview = useFilePreview(inv?.document?.id, !!inv?.document && inv.document.kind !== "spreadsheet");

  const field = (name: string): Field => (inv?.extraction?.[name] as Field) ?? { value: null, confidence: 0, evidence: null, page: null };
  const changed = Object.entries(draft).filter(([k, v]) => v !== (field(k).value ?? ""));

  async function save() {
    if (!changed.length) return;
    setSaving(true);
    try {
      const body = Object.fromEntries(changed.map(([k, v]) => [k, v.trim() === "" ? null : v.trim()]));
      setInv(await api.patch<InvoiceDetail>(`/invoices/${params.id}`, body));
      setDraft({});
      setMsg(`Saved ${changed.length} correction${changed.length === 1 ? "" : "s"}. The checks ran again on the new values.`);
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
      setMsg(resolved ? "Marked as checked." : "Reopened.");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  if (!inv) return err ? <Alert tone="err" title="Could not load this invoice">{err}</Alert> : <Loading rows={8} />;

  const notes = inv.extraction?.notes ?? [];
  const byField = new Map<string, Issue[]>();
  inv.issues.forEach((i) => { if (i.field && !i.resolved) byField.set(i.field, [...(byField.get(i.field) ?? []), i]); });
  const open = inv.issues.filter((i) => !i.resolved);
  const openErrors = open.filter((i) => i.severity === "error");
  const sevOrder = { error: 0, warning: 1, info: 2 } as const;
  const issues = [...inv.issues].sort((a, b) => Number(a.resolved) - Number(b.resolved) || sevOrder[a.severity] - sevOrder[b.severity]);

  // Arithmetic, from the values on screen (including unsaved edits).
  const cur = (k: string) => num(draft[k] ?? field(k).value);
  const sub = cur("subtotal"), tax = cur("tax"), tot = cur("total");
  const linesSum = inv.line_items.length && inv.line_items.every((l) => num(l.amount) !== null)
    ? inv.line_items.reduce((a, l) => a + (num(l.amount) ?? 0), 0) : null;
  const linesOk = linesSum === null || sub === null ? null : Math.abs(linesSum - sub) <= TOL;
  const totalOk = sub === null || tot === null ? null : Math.abs(sub + (tax ?? 0) - tot) <= TOL;
  const currency = draft.currency ?? inv.currency;
  const pageHash = inv.document?.kind === "pdf" ? `#page=${inv.page_start}` : "";

  return (
    <>
      <PageHead
        crumbs={[{ href: "/documents", label: "Documents" }, ...(inv.document ? [{ href: `/documents/${inv.document.id}`, label: inv.document.filename }] : [])]}
        eyebrow={inv.supplier_name ?? "Supplier not found"}
        title={<>Invoice <span className="mono" style={{ fontSize: "0.92em" }}>{inv.invoice_number ?? "(number missing)"}</span></>}
        actions={
          <>
            <button className="ghost" onClick={() => setDraft({})} disabled={!changed.length}>Undo edits</button>
            <button className="primary" onClick={save} disabled={!changed.length || saving}>
              <Icon name="check" size={15} />{saving ? "Saving…" : changed.length ? `Save ${changed.length} correction${changed.length === 1 ? "" : "s"}` : "Save corrections"}
            </button>
          </>
        }
      >
        <span className="row" style={{ gap: 8 }}>
          <Pill status={inv.review_status} />
          <MethodTag method={inv.extraction_method} />
          <span className="muted small">pages {inv.page_start === inv.page_end ? inv.page_start : `${inv.page_start}–${inv.page_end}`} · total <Money value={inv.total} currency={inv.currency} /></span>
        </span>
      </PageHead>

      {msg && <Alert tone="ok">{msg}</Alert>}
      {err && <Alert tone="err" title="Could not save">{err}</Alert>}
      {openErrors.length > 0 ? (
        <Alert tone="warn" title={`${openErrors.length} thing${openErrors.length === 1 ? "" : "s"} to check before this invoice is approved`}>
          Compare the highlighted fields with the original, then correct them or mark the issue as checked.
        </Alert>
      ) : (
        <Alert tone="ok" title="All blocking checks pass">{open.length ? `${open.length} note${open.length === 1 ? "" : "s"} below for information.` : "Nothing needs your attention."}</Alert>
      )}

      <div className="grid split">
        <div className="stack">
          <section className="card">
            <div className="card-h"><h2>Extracted fields</h2><span className="sub">Edit any value; the quote under it is where it was found</span></div>
            <div className="fields">
              {FIELDS.map((fd) => {
                const f = field(fd.name);
                const fi = byField.get(fd.name) ?? [];
                const value = draft[fd.name] ?? f.value ?? "";
                const dirty = draft[fd.name] !== undefined && draft[fd.name] !== (f.value ?? "");
                const hasErr = fi.some((i) => i.severity === "error");
                const vision = notes.includes(`VISION_UNVERIFIED:${fd.name}`);
                return (
                  <div key={fd.name} className={`frow ${dirty ? "dirty" : hasErr ? "err" : ""}`}>
                    <label className="k" htmlFor={`f-${fd.name}`}>
                      <span>{fd.label}{fd.required && <span className="faint" title="Required"> *</span>}</span>
                      {f.value !== null && !dirty && <Conf value={f.confidence} />}
                    </label>
                    <div className="v">
                      <input id={`f-${fd.name}`} value={value} placeholder={`not found · ${fd.hint}`} onChange={(e) => setDraft({ ...draft, [fd.name]: e.target.value })} />
                      {(f.evidence || vision || dirty) && (
                        <div className="meta">
                          {dirty ? <span className="muted">Changed from <span className="mono">{f.value ?? "(empty)"}</span>; not saved yet</span> : (
                            <>
                              {f.evidence && <span className="evidence" title={f.evidence}>{f.page && <span className="faint">p.{f.page} · </span>}“{f.evidence}”</span>}
                              {vision && <span className="tag llm" title="Read from the page image; the scanned text did not confirm it"><Icon name="eye" size={11} />read from image</span>}
                            </>
                          )}
                        </div>
                      )}
                      {!dirty && fi.map((i) => (
                        <div key={i.id} className={`fnote ${i.severity}`}><Icon name={i.severity === "error" ? "alert" : "info"} size={13} /><span>{i.message}</span></div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="card">
            <div className="card-h"><h2>Do the numbers add up?</h2><span className="sub">Tolerance ±0.02</span></div>
            <div className="card-b grid cols-2" style={{ gap: 16 }}>
              <div className="math">
                {linesSum !== null && <><span className="lbl">Line items ({inv.line_items.length})</span><Money value={linesSum.toFixed(2)} currency={currency} /></>}
                <span className="lbl">Subtotal</span><Money value={sub?.toFixed(2)} currency={currency} />
                <span className="lbl">+ Tax</span><Money value={tax?.toFixed(2) ?? null} currency={currency} />
                <span className="lbl total">= Total</span><span className="total"><Money value={tot?.toFixed(2)} currency={currency} /></span>
              </div>
              <div className="grid" style={{ gap: 8, alignContent: "start" }}>
                <Verdict ok={linesOk} yes="Line items add up to the subtotal" no={`Line items add up to ${linesSum?.toFixed(2)}, not ${sub?.toFixed(2)}`} unknown="No line amounts to compare" />
                <Verdict ok={totalOk} yes="Subtotal + tax equals the total" no={`Subtotal + tax is ${sub !== null ? (sub + (tax ?? 0)).toFixed(2) : "?"}, not ${tot?.toFixed(2)}`} unknown="Subtotal or total missing" />
              </div>
            </div>
          </section>

          <section className="card">
            <div className="card-h"><h2>Line items</h2><span className="sub">{inv.line_items.length} read</span></div>
            {inv.line_items.length === 0 ? <Empty title="No line items read" /> : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>#</th><th>Description</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Amount</th></tr></thead>
                  <tbody>
                    {inv.line_items.map((li) => {
                      const q = num(li.quantity), p = num(li.unit_price), a = num(li.amount);
                      const bad = q !== null && p !== null && a !== null && Math.abs(q * p - a) > TOL;
                      return (
                        <tr key={li.line_no}>
                          <td className="muted num">{li.line_no}</td>
                          <td>{li.description ?? <span className="faint">—</span>}</td>
                          <td className="num">{li.quantity ?? "—"}</td>
                          <td className="num"><Money value={li.unit_price} /></td>
                          <td className="num" title={bad ? `qty × price = ${(q! * p!).toFixed(2)}` : undefined} style={bad ? { color: "var(--err)" } : undefined}><Money value={li.amount} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <div className="stack sticky">
          {inv.document && inv.document.kind !== "spreadsheet" && (
            <section className="card">
              <div className="card-h">
                <h2>Original</h2><span className="sub">page {inv.page_start}{inv.page_end !== inv.page_start && `–${inv.page_end}`}</span>
                <span className="spacer" /><Link href={`/documents/${inv.document.id}`} className="small">Open document</Link>
              </div>
              <div className="viewer">
                {!preview ? <div className="card-b"><Loading rows={3} /></div>
                  : inv.document.kind === "pdf" ? <iframe src={`${preview}${pageHash}`} title="Original invoice" style={{ height: "62vh" }} />
                    : <img src={preview} alt="Original invoice" />}
              </div>
            </section>
          )}

          <section className="card">
            <div className="card-h"><h2>Checks</h2><span className="sub">{open.length} open · {inv.issues.length - open.length} checked</span></div>
            {issues.length === 0 ? <Empty icon="check" title="No problems found" /> : issues.map((i) => {
              const matches = Array.isArray(i.details?.matches) ? (i.details.matches as string[]) : [];
              return (
                <div key={i.id} className={`issue ${i.severity} ${i.resolved ? "resolved" : ""}`}>
                  <span className="stripe" />
                  <div>
                    <div className="top">
                      <b style={{ fontWeight: 600 }}>{issueLabel(i.code)}</b>
                      <span className="code">{i.code}</span>
                      <span className="spacer" />
                      {i.resolved && <span className="pill ok">checked</span>}
                      {i.severity === "error" && (
                        <button className="sm" onClick={() => resolve(i, !i.resolved)}>{i.resolved ? "Reopen" : "Mark checked"}</button>
                      )}
                    </div>
                    <div className="msg">{i.message}</div>
                    {matches.length > 0 && (
                      <div className="small muted" style={{ marginTop: 4 }}>
                        Compare with: {matches.map((m, n) => <span key={m}>{n > 0 && ", "}<Link href={`/invoices/${m}`}>invoice {n + 1}</Link></span>)}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </section>

          {inv.corrections.length > 0 && (
            <section className="card">
              <div className="card-h"><h2>Correction history</h2></div>
              <ul className="tl">
                {inv.corrections.map((c, n) => (
                  <li key={n}>
                    <span className="dot run" />
                    <span className="row" style={{ gap: 6 }}>
                      <b style={{ fontWeight: 500 }}>{FIELDS.find((f) => f.name === c.field)?.label ?? c.field}</b>
                      <span className="mono faint" style={{ textDecoration: "line-through" }}>{c.old_value ?? "(empty)"}</span>→<span className="mono">{c.new_value ?? "(empty)"}</span>
                    </span>
                    <span className="when">{ago(c.created_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {notes.length > 0 && (
            <details className="card card-b small muted">
              <summary style={{ cursor: "pointer" }}>Extraction notes ({notes.length})</summary>
              <div className="chips" style={{ marginTop: 10 }}>{notes.map((n) => <span key={n} className="kind">{n}</span>)}</div>
            </details>
          )}
        </div>
      </div>
    </>
  );
}

function Verdict({ ok, yes, no, unknown }: { ok: boolean | null; yes: string; no: string; unknown: string }) {
  if (ok === null) return <span className="verdict muted" style={{ fontWeight: 400 }}><Icon name="info" size={15} />{unknown}</span>;
  return <span className={`verdict ${ok ? "ok" : "bad"}`}><Icon name={ok ? "check" : "x"} size={15} />{ok ? yes : no}</span>;
}

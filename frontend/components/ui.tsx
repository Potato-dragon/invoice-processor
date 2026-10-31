"use client";
// Shared presentation pieces: status pills, the four-stage pipeline stepper,
// confidence meters, money, KPI tiles, small charts, icons and the upload box.
import Link from "next/link";
import { ReactNode, useEffect, useRef, useState } from "react";
import { api, ApiError, IN_FLIGHT, STAGES } from "@/lib/api";

// ------------------------------------------------------------------ labels

const STATUS: Record<string, [string, string]> = {
  UPLOADED: ["Queued", "run"], PARSING: ["Reading", "run"], EXTRACTING: ["Extracting", "run"],
  VALIDATING: ["Checking", "run"], INDEXING: ["Indexing", "run"],
  COMPLETED: ["Completed", "ok"], NEEDS_REVIEW: ["Needs review", "warn"], FAILED: ["Failed", "err"],
  AUTO_OK: ["Auto-approved", "ok"], CORRECTED: ["Corrected", "ok"], PENDING: ["Pending", "info"],
  MATCH: ["Match", "ok"], MISMATCH: ["Mismatch", "err"], NO_MATCH: ["Not found", "warn"],
  error: ["Error", "err"], warning: ["Warning", "warn"], info: ["Info", "info"],
};

export function statusLabel(s: string): string {
  return STATUS[s]?.[0] ?? s.replace(/_/g, " ").toLowerCase();
}

export function Pill({ status, children }: { status: string; children?: ReactNode }) {
  const [label, tone] = STATUS[status] ?? [status, "info"];
  return <span className={`pill ${tone}`}>{children ?? label}</span>;
}

export const METHOD: Record<string, [string, string, string]> = {
  rules: ["Rules", "rules", "Read by the rules engine; no AI call."],
  llm_primary: ["Gemma 31B", "llm", "Some fields came from Gemma 4 31B (text)."],
  llm_fallback: ["Gemma 26B", "llm", "Some fields came from the fallback model, Gemma 4 26B."],
  llm_vision: ["Gemma vision", "llm", "The scan was unreadable, so Gemma read the page image."],
  manual: ["Corrected by hand", "manual", "A person corrected one or more fields."],
};

export function MethodTag({ method }: { method: string | null | undefined }) {
  if (!method) return <span className="faint">—</span>;
  const [label, cls, title] = METHOD[method] ?? [method, "", method];
  return <span className={`tag ${cls}`} title={title}>{cls === "llm" && <Icon name="spark" size={11} />}{label}</span>;
}

export const ISSUE_LABEL: Record<string, string> = {
  MISSING_FIELD: "Missing field", LINE_ITEMS_SUBTOTAL_MISMATCH: "Lines ≠ subtotal", SUBTOTAL_TAX_TOTAL_MISMATCH: "Subtotal + tax ≠ total",
  NEGATIVE_AMOUNT: "Negative amount", INVALID_DATE: "Date problem", CURRENCY_AMBIGUOUS: "Currency unclear",
  LOW_CONFIDENCE: "Low confidence", LOW_OCR_CONFIDENCE: "Poor scan", EVIDENCE_NOT_FOUND: "Not in document",
  DUPLICATE_EXACT: "Duplicate", DUPLICATE_FUZZY: "Possible duplicate", CROSS_TOTAL_MISMATCH: "Cross-check: total",
  CROSS_TAX_MISMATCH: "Cross-check: tax", CROSS_SUBTOTAL_MISMATCH: "Cross-check: subtotal", CROSS_DATE_MISMATCH: "Cross-check: date",
  CROSS_CURRENCY_MISMATCH: "Cross-check: currency", CROSS_NOT_FOUND: "Cross-check: not found",
};
export const issueLabel = (code: string) => ISSUE_LABEL[code] ?? code.replace(/_/g, " ").toLowerCase();

export const ERROR_LABEL: Record<string, string> = {
  FILE_CORRUPT: "Corrupt file", FILE_ENCRYPTED: "Password-protected", FILE_EMPTY: "Empty file", FILE_TYPE_UNSUPPORTED: "Unsupported type",
  FILE_TOO_LARGE: "File too large", PAGE_LIMIT_EXCEEDED: "Too many pages", OCR_FAILED: "Scan unreadable",
  SPREADSHEET_PARSE_FAILED: "Spreadsheet unreadable", LLM_RATE_LIMITED: "AI quota reached", LLM_UNAVAILABLE: "AI unavailable",
  INTERNAL_ERROR: "Internal error",
};
export const errorLabel = (code: string) => ERROR_LABEL[code] ?? code.replace(/_/g, " ").toLowerCase();

// ------------------------------------------------------------------ formatting

export function Money({ value, currency }: { value: string | null | undefined; currency?: string | null }) {
  if (value === null || value === undefined || value === "") return <span className="faint">—</span>;
  const n = Number(value);
  const txt = Number.isFinite(n) ? n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : value;
  return <span className="money">{txt}{currency && <span className="cur">{currency}</span>}</span>;
}

export function ago(iso: string): string {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString();
}

export function ms(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  if (v < 60000) return `${(v / 1000).toFixed(1)} s`;
  return `${Math.floor(v / 60000)} m ${Math.round((v % 60000) / 1000)} s`;
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

// ------------------------------------------------------------------ pipeline stepper

const STAGE_LABEL: Record<string, string> = { parse: "Read", extract: "Extract", validate: "Check", index: "Index" };

/** parse -> extract -> validate -> index, with the state of each step. */
export function Steps({ status, stage, durations, mini }: {
  status: string; stage: string | null; durations?: Record<string, number>; mini?: boolean;
}) {
  const at = stage ? STAGES.indexOf(stage) : -1;
  const finished = status === "COMPLETED" || status === "NEEDS_REVIEW";
  const state = (i: number) => {
    if (finished) return "done";
    if (status === "FAILED") return i < at ? "done" : i === at ? "failed" : "todo";
    if (status === "UPLOADED") return i === 0 ? "active" : "todo";
    return i < at ? "done" : i === at ? "active" : "todo";
  };
  return (
    <div className={`steps ${mini ? "mini" : ""}`} title={mini ? `${statusLabel(status)}${stage ? ` · ${stage}` : ""}` : undefined}>
      {STAGES.map((s, i) => (
        <div key={s} className={`step ${state(i)}`}>
          <div className="bar"><i /></div>
          {!mini && (
            <div className="lbl">
              <b>{STAGE_LABEL[s]}</b>
              {durations?.[s] !== undefined && <span className="ms">{ms(durations[s])}</span>}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ meters and charts

export function Conf({ value }: { value: number }) {
  const cls = value < 0.6 ? "low" : value < 0.8 ? "mid" : "";
  return (
    <span className={`conf ${cls}`} title="How sure the system is about this value">
      <span className="m"><i style={{ width: `${Math.round(value * 100)}%` }} /></span>
      {Math.round(value * 100)}%
    </span>
  );
}

export function Kpi({ label, value, unit, detail, tone, href }: {
  label: string; value: ReactNode; unit?: string; detail?: ReactNode; tone?: "ok" | "warn" | "err" | "run"; href?: string;
}) {
  const body = (
    <>
      <span className="l">{label}</span>
      <span className="n">{value}{unit && <small>{unit}</small>}</span>
      {detail && <span className="d">{detail}</span>}
    </>
  );
  const cls = `kpi ${tone ? `tone-${tone}` : ""}`;
  return href ? <Link href={href} className={cls}>{body}</Link> : <div className={cls}>{body}</div>;
}

export type Segment = { label: string; value: number; color: string };

export function StackBar({ segments }: { segments: Segment[] }) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  return (
    <div className="grid" style={{ gap: 10 }}>
      <div className="stackbar" role="img" aria-label={segments.map((s) => `${s.label} ${s.value}`).join(", ")}>
        {total > 0 && segments.filter((s) => s.value > 0).map((s) => <span key={s.label} style={{ width: `${(s.value / total) * 100}%`, background: s.color }} />)}
      </div>
      <div className="legend">
        {segments.map((s) => <span key={s.label}><i style={{ background: s.color }} />{s.label} <b>{s.value}</b></span>)}
      </div>
    </div>
  );
}

export function BarList({ items, color, onPick }: { items: { label: string; value: number; key?: string }[]; color?: string; onPick?: (key: string) => void }) {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="barlist">
      {items.map((i) => (
        <div key={i.key ?? i.label} className="it" style={onPick ? { cursor: "pointer" } : undefined} onClick={onPick ? () => onPick(i.key ?? i.label) : undefined}>
          <span className="truncate" style={{ maxWidth: "100%" }}>{i.label}</span>
          <span className="v">{i.value}</span>
          <span className="track"><i style={{ width: `${(i.value / max) * 100}%`, background: color }} /></span>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ alerts, empty states, headers

export function Alert({ tone, title, children }: { tone: "err" | "ok" | "warn" | "info"; title?: ReactNode; children?: ReactNode }) {
  const icon = tone === "ok" ? "check" : tone === "info" ? "info" : "alert";
  return (
    <div className={`alert ${tone}`} role={tone === "err" ? "alert" : "status"}>
      <Icon name={icon} size={16} />
      <div className="body">{title && <b>{title}</b>}{children && <span>{children}</span>}</div>
    </div>
  );
}

export function Empty({ icon = "inbox", title, children }: { icon?: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon name={icon} size={28} />
      <b>{title}</b>
      {children && <span className="small">{children}</span>}
    </div>
  );
}

export function PageHead({ crumbs, title, children, actions, eyebrow }: {
  crumbs?: { href: string; label: string }[]; title: ReactNode; children?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode;
}) {
  return (
    <header className="head">
      <div className="titles">
        {crumbs && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => <span key={c.href} className="row" style={{ gap: 6 }}>{i > 0 && <span className="faint">/</span>}<Link href={c.href}>{c.label}</Link></span>)}
          </nav>
        )}
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return <div className="card card-b grid" style={{ gap: 12 }}>{Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}</div>;
}

// ------------------------------------------------------------------ upload

type UploadResult = { id?: string; filename: string; status: string; error?: { code: string; message: string }; duplicate_of?: string };
const ACCEPT = ".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv";

export function Dropzone({ onDone, compact }: { onDone?: () => void; compact?: boolean }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<UploadResult[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function send(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    setResults(null);
    setErr(null);
    try {
      const out: UploadResult[] = [];
      for (let i = 0; i < files.length; i += 20) out.push(...(await api.upload(files.slice(i, i + 20))));
      setResults(out);
      onDone?.();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.message} (${e.code})` : (e as Error).message);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div>
      <div
        className={`drop ${over ? "over" : ""}`}
        role="button"
        tabIndex={0}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); send(Array.from(e.dataTransfer.files)); }}
      >
        <span className="ic"><Icon name={busy ? "clock" : "upload"} size={22} /></span>
        <span className="t">
          <b>{busy ? "Uploading…" : "Drop invoices here, or click to choose files"}</b>
          {!compact && <span>PDF, scans (JPG, PNG, TIFF) and spreadsheets (XLSX, XLS, CSV). Several at once is fine; each is processed in the background.</span>}
        </span>
        <input id="upload-input" ref={input} type="file" multiple accept={ACCEPT} hidden onChange={(e) => send(Array.from(e.target.files ?? []))} />
      </div>
      {err && <div style={{ marginTop: 10 }}><Alert tone="err" title="Upload failed">{err}</Alert></div>}
      {results && (
        <div className="upl">
          {results.map((r, i) => (
            <div key={i} className="it">
              <Icon name={r.error ? "alert" : "check"} size={14} />
              {r.id && !r.error ? <Link href={`/documents/${r.id}`} className="mono">{r.filename}</Link> : <span className="mono">{r.filename}</span>}
              {r.error ? <Pill status="FAILED">{errorLabel(r.error.code)}</Pill> : <Pill status={IN_FLIGHT.has(r.status) ? "UPLOADED" : r.status} />}
              <span className="muted small">{r.error?.message ?? (r.duplicate_of ? "This exact file was uploaded before." : "Accepted; processing has started.")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ file preview

/** The original file is fetched through the proxy (which adds the key) and shown from a blob URL. */
export function useFilePreview(docId: string | undefined, enabled: boolean): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!docId || !enabled) return;
    let made: string | null = null;
    let live = true;
    fetch(api.fileUrl(docId)).then(async (r) => {
      if (!r.ok || !live) return;
      made = URL.createObjectURL(await r.blob());
      setUrl(made);
    }).catch(() => undefined);
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [docId, enabled]);
  return url;
}

// ------------------------------------------------------------------ icons (inline, stroke = currentColor)

export type IconName = "home" | "files" | "review" | "search" | "compare" | "upload" | "check" | "alert" | "info" | "clock"
  | "inbox" | "spark" | "refresh" | "arrow" | "doc" | "sheet" | "image" | "x" | "eye";

const PATHS: Record<IconName, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  files: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M9 13h6M9 17h4",
  review: "M9 11l2 2 4-4M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3",
  compare: "M8 3v18M16 3v18M3 8h5M16 16h5M3 16h5M16 8h5",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3",
  check: "M20 6 9 17l-5-5",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1z",
  spark: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z",
  refresh: "M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5",
  arrow: "M5 12h14M13 6l6 6-6 6",
  doc: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  sheet: "M4 4h16v16H4zM4 10h16M4 15h16M10 4v16",
  image: "M4 4h16v16H4zM4 16l5-5 4 4 3-3 4 4M15 9h.01",
  x: "M18 6 6 18M6 6l12 12",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
};

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

export function KindIcon({ kind }: { kind: string }) {
  return <Icon name={kind === "spreadsheet" ? "sheet" : kind === "image" ? "image" : "doc"} size={16} />;
}

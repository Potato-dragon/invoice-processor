// Small typed client for the backend (through /api/proxy, which adds the key).

export type Doc = {
  id: string; filename: string; kind: string; status: string; current_stage: string | null;
  error_code: string | null; error_message: string | null; page_count: number | null; size_bytes: number;
  created_at: string; updated_at: string; invoice_count?: number; open_errors?: number;
};
export type InvoiceSummary = {
  id: string; document_id: string; page_start: number; page_end: number; review_status: string;
  invoice_number: string | null; invoice_date: string | null; supplier_name: string | null; customer_name: string | null;
  subtotal: string | null; tax: string | null; total: string | null; currency: string | null; extraction_method: string | null;
  open_errors?: number; score?: number | null; filename?: string | null;
};
export type Field = { value: string | null; confidence: number; evidence: string | null; page: number | null };
export type Issue = {
  id: string; document_id: string; invoice_id: string | null; code: string; severity: "error" | "warning" | "info";
  field: string | null; message: string; details: Record<string, unknown>; resolved: boolean; created_at: string;
};
export type InvoiceDetail = InvoiceSummary & {
  document: { id: string; filename: string; kind: string; status: string; page_count: number | null } | null;
  extraction: Record<string, Field | unknown> & { notes?: string[]; method?: string };
  line_items: { line_no: number; description: string | null; quantity: string | null; unit_price: string | null; amount: string | null }[];
  issues: Issue[];
  corrections: { field: string; old_value: string | null; new_value: string | null; created_at: string }[];
};
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };
export type Stats = {
  documents: {
    total: number; by_status: Record<string, number>; by_error_code: Record<string, number>; by_kind: Record<string, number>;
    success_rate: number | null; failure_rate: number | null;
  };
  invoices: { total: number; by_review_status: Record<string, number>; by_extraction_method: Record<string, number> };
  stages: Record<string, { runs: number; avg_ms: number; max_ms: number | null }>;
  avg_document_processing_ms: number | null;
  issues_by_code: Record<string, number>;
};
export type DocEvent = {
  id: string; stage: string; event: string; error_code: string | null; detail: Record<string, unknown>;
  duration_ms: number | null; invoice_id: string | null; created_at: string;
};
export type ApiErr = { code: string; message: string };

export class ApiError extends Error {
  code: string;
  constructor(e: ApiErr) {
    super(e.message);
    this.code = e.code;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: { error?: ApiErr } = {};
    try {
      body = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(body.error ?? { code: "HTTP_" + res.status, message: res.statusText || "Request failed" });
  }
  return res.json() as Promise<T>;
}

const base = "/api/proxy";

export function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const api = {
  get: <T>(path: string) => fetch(base + path, { cache: "no-store" }).then((r) => handle<T>(r)),
  post: <T>(path: string, body?: unknown) =>
    fetch(base + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) }).then((r) => handle<T>(r)),
  patch: <T>(path: string, body: unknown) =>
    fetch(base + path, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then((r) => handle<T>(r)),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return fetch(base + "/documents", { method: "POST", body: fd }).then((r) =>
      handle<{ id: string; filename: string; status: string; error?: ApiErr; duplicate_of?: string }[]>(r));
  },
  fileUrl: (docId: string) => `${base}/documents/${docId}/file`,
};

export const IN_FLIGHT = new Set(["UPLOADED", "PARSING", "EXTRACTING", "VALIDATING", "INDEXING"]);
export const STAGES = ["parse", "extract", "validate", "index"];


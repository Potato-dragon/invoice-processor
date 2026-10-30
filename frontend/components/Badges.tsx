import { IN_FLIGHT, STAGES } from "@/lib/api";

const STATUS_CLASS: Record<string, string> = {
  COMPLETED: "b-ok", AUTO_OK: "b-ok", CORRECTED: "b-ok", MATCH: "b-ok",
  NEEDS_REVIEW: "b-warn", MISMATCH: "b-err", NO_MATCH: "b-warn", PENDING: "b-info",
  FAILED: "b-err", error: "b-err", warning: "b-warn", info: "b-info",
};

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_CLASS[status] ?? (IN_FLIGHT.has(status) ? "b-run" : "b-info");
  return <span className={`badge ${cls}`}>{status.replace("_", " ")}</span>;
}

/** Progress through parse -> extract -> validate -> index. */
export function StageProgress({ status, stage }: { status: string; stage: string | null }) {
  let pct = 0;
  if (status === "COMPLETED" || status === "NEEDS_REVIEW") pct = 100;
  else if (status === "UPLOADED") pct = 4;
  else if (stage) pct = Math.round(((STAGES.indexOf(stage) + 0.5) / STAGES.length) * 100);
  const cls = status === "FAILED" ? "fail" : pct === 100 ? "done" : "";
  return (
    <div className={`progress ${cls}`} title={stage ?? status}>
      <span style={{ width: `${status === "FAILED" ? 100 : pct}%` }} />
    </div>
  );
}

export function Confidence({ value }: { value: number }) {
  return <span className={`conf ${value < 0.6 ? "low" : ""}`}>{Math.round(value * 100)}%</span>;
}

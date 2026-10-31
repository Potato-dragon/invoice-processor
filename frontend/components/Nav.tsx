"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, IN_FLIGHT, Stats } from "@/lib/api";
import { Icon, IconName } from "@/components/ui";

const LINKS: { href: string; label: string; icon: IconName; count?: "review" | "busy" }[] = [
  { href: "/", label: "Overview", icon: "home" },
  { href: "/documents", label: "Documents", icon: "files", count: "busy" },
  { href: "/review", label: "Review queue", icon: "review", count: "review" },
  { href: "/search", label: "Search", icon: "search" },
  { href: "/crosschecks", label: "Cross-checks", icon: "compare" },
];

function Logo() {
  return (
    <svg width="30" height="30" viewBox="0 0 32 32" aria-hidden="true">
      <rect x="1" y="1" width="30" height="30" rx="8" fill="#4fc1b2" />
      <path d="M10 8h9l4 4v12H10z" fill="#0f2524" />
      <path d="M13 15h7M13 18.5h7M13 22h4" stroke="#4fc1b2" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export default function Nav() {
  const path = usePathname();
  const [stats, setStats] = useState<Stats | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () => api.get<Stats>("/stats").then((s) => { if (live) { setStats(s); setDown(false); } }).catch(() => live && setDown(true));
    load();
    const t = setInterval(load, 10000);
    return () => { live = false; clearInterval(t); };
  }, [path]);

  const by = stats?.documents.by_status ?? {};
  const busy = Object.entries(by).filter(([k]) => IN_FLIGHT.has(k)).reduce((a, [, v]) => a + v, 0);
  const review = stats?.invoices.by_review_status?.NEEDS_REVIEW ?? 0;

  return (
    <aside className="rail">
      <Link href="/" className="brand">
        <Logo />
        <span><b>Invoice AI</b><small>Document intelligence</small></span>
      </Link>
      <nav aria-label="Main">
        {LINKS.map((l) => {
          const active = l.href === "/" ? path === "/" : path.startsWith(l.href) || (l.href === "/documents" && path.startsWith("/invoices"));
          const n = l.count === "review" ? review : l.count === "busy" ? busy : 0;
          return (
            <Link key={l.href} href={l.href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}>
              <Icon name={l.icon} size={17} />
              <span className="label-long">{l.label}</span>
              {n > 0 && <span className={`count ${l.count === "review" ? "hot" : ""}`} title={l.count === "review" ? "Invoices waiting for review" : "Files being processed"}>{n}</span>}
            </Link>
          );
        })}
      </nav>
      <div className="rail-foot">
        <span className={`live ${down ? "down" : ""}`}><i />{down ? "API not reachable" : busy > 0 ? `${busy} file${busy === 1 ? "" : "s"} processing` : "All files processed"}</span>
        <div className="flow" aria-label="Pipeline stages"><span>read</span>→<span>extract</span>→<span>check</span>→<span>index</span></div>
        <span>Rules first. Gemma 4 only for fields the rules can’t settle.</span>
      </div>
    </aside>
  );
}

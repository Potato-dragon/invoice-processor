"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Documents" },
  { href: "/review", label: "Review" },
  { href: "/search", label: "Search" },
  { href: "/crosschecks", label: "Cross-checks" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={(l.href === "/" ? path === "/" : path.startsWith(l.href)) ? "active" : ""}>
          {l.label}
        </Link>
      ))}
    </nav>
  );
}

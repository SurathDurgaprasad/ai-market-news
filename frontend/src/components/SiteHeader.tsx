"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/#happening-now", label: "Now", area: "/" },
  { href: "/#biggest", label: "Biggest", area: "/" },
  { href: "/#players", label: "Players", area: "/players" },
  { href: "/#latest-developments", label: "Latest", area: "/" },
  { href: "/admin/sources", label: "Sources", area: "/admin" },
];

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  // Only whole areas are marked current; the homepage anchors are sections of one page.
  const current = pathname.startsWith("/admin") ? "/admin" : pathname.startsWith("/players") ? "/players" : "";

  return (
    <header className="z-40 border-b border-line bg-canvas md:sticky md:top-0">
      <div className="intel-shell flex min-h-12 flex-wrap items-center justify-between gap-x-6 gap-y-1 py-2">
        <Link href="/" className="group inline-flex items-center gap-2.5" aria-label="AI World Intelligence, market overview">
          <span
            className="grid h-6 w-6 place-items-center rounded-[4px] border border-accent/50 bg-accent/10 text-[10px] font-bold tracking-tight text-accent"
            aria-hidden="true"
          >
            AI
          </span>
          <span className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink group-hover:text-accent">
            World Intelligence
          </span>
          <span className="hidden border-l border-line pl-2.5 text-[12px] text-muted md:inline">
            AI market intelligence
          </span>
        </Link>
        <nav aria-label="Primary">
          <ul className="flex flex-wrap items-center gap-x-1 text-[13px]">
            {NAV.map((item) => {
              const active = current !== "" && item.area === current;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`rounded px-2.5 py-1.5 transition-colors hover:bg-elevated hover:text-ink ${
                      active ? "bg-elevated text-ink" : "text-muted"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}

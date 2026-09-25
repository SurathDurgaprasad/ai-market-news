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
    <header className="z-40 border-b border-line bg-canvas/95 backdrop-blur-sm md:sticky md:top-0">
      <div className="intel-shell flex min-h-14 flex-wrap items-center justify-between gap-x-6 gap-y-1 py-2">
        <Link href="/" className="group inline-flex items-baseline gap-2" aria-label="AI Market News, home">
          <span className="font-display text-[22px] font-semibold leading-none tracking-[-0.01em] text-ink">
            AI Market News
          </span>
          <span
            className="mb-0.5 hidden h-1.5 w-1.5 rounded-full bg-accent sm:inline-block"
            aria-hidden="true"
          />
        </Link>
        <nav aria-label="Primary">
          <ul className="flex flex-wrap items-center gap-x-0.5 text-[13.5px]">
            {NAV.map((item) => {
              const active = current !== "" && item.area === current;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`rounded px-3 py-1.5 transition-colors hover:bg-elevated hover:text-ink ${
                      active ? "bg-elevated text-ink" : "text-secondary"
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

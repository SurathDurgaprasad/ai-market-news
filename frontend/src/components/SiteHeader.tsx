import Link from "next/link";

const NAV = [
  { href: "/#happening-now", label: "Now" },
  { href: "/#biggest", label: "Biggest" },
  { href: "/#players", label: "Players" },
  { href: "/#latest-developments", label: "Latest" },
  { href: "/admin/sources", label: "Sources" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-line bg-canvas">
      <div className="intel-shell flex min-h-12 flex-wrap items-center justify-between gap-x-6 gap-y-1 py-2">
        <Link
          href="/"
          className="text-[13px] font-semibold uppercase tracking-[0.16em] text-ink hover:text-accent"
        >
          AI World Intelligence
        </Link>
        <nav aria-label="Primary">
          <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-[13px] text-muted">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link href={item.href} className="hover:text-ink">
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}

import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-line">
      <div className="intel-shell flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2 py-6 text-[12.5px] text-muted">
        <p>
          <span className="font-display text-[15px] text-secondary">AI Market News</span>
          <span className="mx-2" aria-hidden="true">·</span>
          Every development links to its original sources. Repeated coverage is counted once. Times in UTC.
        </p>
        <Link href="/admin/sources" className="hover:text-ink">
          Sources we follow
        </Link>
      </div>
    </footer>
  );
}

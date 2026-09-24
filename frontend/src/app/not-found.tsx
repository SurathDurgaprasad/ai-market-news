import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="intel-shell py-16 text-center">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">404</p>
        <h1 className="mt-2 text-2xl font-semibold text-ink">Not found</h1>
        <p className="mt-2 text-muted">This event or page does not exist.</p>
        <Link href="/" className="mt-6 inline-block text-accent hover:underline">
          ← Back to overview
        </Link>
      </div>
    </main>
  );
}

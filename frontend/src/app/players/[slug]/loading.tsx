export default function PlayerLoading() {
  return (
    <main className="flex-1 bg-canvas text-ink" aria-busy="true" aria-label="Loading player">
      <div className="intel-shell py-6 lg:py-8">
        <p className="sr-only" role="status">Loading this organization&apos;s developments…</p>
        <div className="mb-6 h-4 w-32 animate-pulse rounded bg-elevated" />
        <div className="mb-8 border-b border-line pb-5">
          <div className="h-3 w-20 animate-pulse rounded bg-elevated" />
          <div className="mt-2 h-8 w-56 animate-pulse rounded bg-elevated" />
          <div className="mt-3 h-3 w-80 max-w-full animate-pulse rounded bg-elevated" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {Array.from({ length: 6 }).map((_, idx) => (
            <div key={idx} className="h-44 rounded-md border border-line bg-surface" />
          ))}
        </div>
      </div>
    </main>
  );
}

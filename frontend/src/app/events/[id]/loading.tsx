export default function EventDetailLoading() {
  return (
    <main className="flex-1 bg-canvas text-ink" aria-busy="true" aria-label="Loading event">
      <div className="intel-shell py-6 lg:py-8">
        <p className="sr-only" role="status">Loading the event record…</p>
        <div className="mb-6 h-4 w-24 animate-pulse rounded bg-elevated" />
        <div className="mb-3 h-3 w-40 animate-pulse rounded bg-elevated" />
        <div className="mb-8 h-10 w-5/6 max-w-3xl animate-pulse rounded bg-elevated" />
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.9fr)] lg:gap-14">
          <div className="space-y-3">
            <div className="h-4 w-full animate-pulse rounded bg-elevated" />
            <div className="h-4 w-11/12 animate-pulse rounded bg-elevated" />
            <div className="h-4 w-3/4 animate-pulse rounded bg-elevated" />
          </div>
          <div className="h-56 rounded-md border border-line bg-surface" />
        </div>
      </div>
    </main>
  );
}

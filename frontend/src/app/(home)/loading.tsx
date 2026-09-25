function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-elevated ${className}`} />;
}

function Tile({ className = "" }: { className?: string }) {
  return (
    <div className={`space-y-2.5 rounded-[var(--radius-card)] border border-line bg-surface p-4 ${className}`}>
      <Bar className="h-3 w-40" />
      <Bar className="h-5 w-11/12" />
      <Bar className="h-4 w-2/3" />
    </div>
  );
}

// Mirrors the overview layout: lead development, supporting grid, signal panel.
export default function Loading() {
  return (
    <main className="flex-1 bg-canvas text-ink" aria-busy="true" aria-label="Loading overview">
      <div className="intel-shell py-5 lg:py-6">
        <p className="sr-only" role="status">Loading the market overview…</p>
        <div className="mb-7 border-b border-line pb-5">
          <Bar className="h-3 w-40" />
          <Bar className="mt-2 h-8 w-80 max-w-full" />
          <Bar className="mt-2 h-3 w-96 max-w-full" />
        </div>
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] xl:grid-cols-[minmax(0,1fr)_420px] xl:gap-10">
          <div className="space-y-3">
            <Bar className="mb-4 h-5 w-56" />
            <div className="space-y-3 rounded-[var(--radius-card)] border border-line bg-surface p-6">
              <Bar className="h-3 w-48" />
              <Bar className="h-7 w-3/4" />
              <Bar className="h-4 w-full" />
              <Bar className="h-4 w-2/3" />
            </div>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {Array.from({ length: 4 }).map((_, idx) => (
                <Tile key={idx} />
              ))}
            </div>
          </div>
          <div className="space-y-3 rounded-[var(--radius-card)] border border-line bg-surface p-4">
            <Bar className="h-5 w-32" />
            {Array.from({ length: 5 }).map((_, idx) => (
              <Bar key={idx} className="h-9 w-full" />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

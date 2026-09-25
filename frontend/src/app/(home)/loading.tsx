function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-elevated ${className}`} />;
}

export default function Loading() {
  return (
    <main className="flex-1 bg-canvas text-ink" aria-busy="true" aria-label="Loading overview">
      <div className="intel-shell py-6 lg:py-8">
        <p className="sr-only" role="status">Loading the market overview…</p>
        <div className="mb-8 border-b border-line pb-5">
          <Bar className="h-7 w-72 max-w-full" />
          <Bar className="mt-2 h-3 w-96 max-w-full" />
        </div>
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)] xl:gap-14">
          <div className="space-y-4">
            <Bar className="h-4 w-48" />
            {Array.from({ length: 4 }).map((_, idx) => (
              <div key={idx} className="space-y-2 border-b border-line pb-4">
                <Bar className="h-3 w-40" />
                <Bar className="h-5 w-full" />
                <Bar className="h-4 w-2/3" />
              </div>
            ))}
          </div>
          <div className="space-y-3">
            <Bar className="h-4 w-32" />
            {Array.from({ length: 6 }).map((_, idx) => (
              <Bar key={idx} className="h-8 w-full" />
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

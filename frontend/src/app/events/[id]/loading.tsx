// Same outline as the loaded event page: story column and facts sidebar.
function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-elevated ${className}`} />;
}

export default function EventDetailLoading() {
  return (
    <main className="flex-1 bg-canvas text-ink" aria-busy="true" aria-label="Loading development">
      <div className="intel-shell py-7 lg:py-9">
        <div className="mx-auto max-w-[1360px]">
          <p className="sr-only" role="status">Loading the development…</p>
          <Bar className="mb-7 h-4 w-28" />
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px] xl:gap-16">
            <div>
              <Bar className="h-3 w-32" />
              <Bar className="mt-4 h-11 w-11/12" />
              <Bar className="mt-5 h-5 w-full" />
              <Bar className="mt-2 h-5 w-3/4" />
              <Bar className="mt-8 aspect-[2/1] w-full" />
            </div>
            <div className="h-64 rounded-md border border-line bg-surface" />
          </div>
        </div>
      </div>
    </main>
  );
}

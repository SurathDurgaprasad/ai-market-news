export default function EventDetailLoading() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="intel-shell py-10">
        <div className="mb-6 h-4 w-40 animate-pulse rounded bg-elevated" />
        <div className="mb-7 aspect-[21/6] max-h-[168px] w-full animate-pulse rounded-lg bg-surface" />
        <div className="mb-3 h-4 w-48 animate-pulse rounded bg-elevated" />
        <div className="mb-8 h-12 w-5/6 max-w-3xl animate-pulse rounded bg-elevated" />
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.95fr)]">
          <div className="h-64 rounded-lg border border-line bg-surface" />
          <div className="h-64 rounded-lg border border-line bg-elevated" />
        </div>
      </div>
    </main>
  );
}

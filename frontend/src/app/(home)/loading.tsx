export default function Loading() {
  return (
    <main className="min-h-screen bg-[#070708] text-white">
      <div className="intel-shell py-10">
        <header className="mb-10 border-b border-white/[0.08] pb-8">
          <div className="h-10 w-80 max-w-full animate-pulse rounded bg-white/10" />
          <div className="mt-4 h-3 w-40 animate-pulse rounded bg-white/10" />
          <div className="mt-3 h-4 w-56 animate-pulse rounded bg-white/5" />
        </header>
        <div className="mb-7 h-4 w-48 animate-pulse rounded bg-white/10" />
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, idx) => (
            <div
              key={idx}
              className="overflow-hidden rounded-lg border border-white/[0.08] bg-[#111114]"
            >
              <div className="aspect-[16/10] max-h-36 w-full animate-pulse bg-white/5" />
              <div className="space-y-3 p-5">
                <div className="h-3 w-20 animate-pulse rounded bg-white/10" />
                <div className="h-5 w-full animate-pulse rounded bg-white/10" />
                <div className="h-5 w-2/3 animate-pulse rounded bg-white/10" />
                <div className="h-4 w-full animate-pulse rounded bg-white/5" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

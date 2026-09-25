// Same outline as the loaded homepage: intro, trending strip, lead story with
// secondary stories, then the biggest developments.
function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded bg-elevated ${className}`} />;
}

export default function Loading() {
  return (
    <main className="flex-1 bg-canvas" aria-busy="true" aria-label="Loading developments">
      <div className="intel-shell pb-6 pt-7 lg:pt-9">
        <Bar className="h-3 w-28" />
        <Bar className="mt-3 h-11 w-[min(100%,34rem)]" />
        <Bar className="mt-3 h-3 w-[min(100%,26rem)]" />
        <div className="mt-6 border-y border-line py-4">
          <Bar className="h-3 w-[min(100%,52rem)]" />
        </div>
        <div className="mt-10 grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-12">
          <div className="lg:col-span-7">
            <Bar className="aspect-[2/1] w-full" />
            <Bar className="mt-5 h-3 w-40" />
            <Bar className="mt-3 h-9 w-11/12" />
            <Bar className="mt-3 h-4 w-3/4" />
          </div>
          <div className="space-y-6 lg:col-span-5 lg:border-l lg:border-line lg:pl-10">
            {[0, 1, 2, 3].map((item) => (
              <div key={item} className="grid grid-cols-[minmax(0,1fr)_7rem] gap-5">
                <div>
                  <Bar className="h-3 w-32" />
                  <Bar className="mt-2.5 h-5 w-full" />
                  <Bar className="mt-2 h-5 w-2/3" />
                </div>
                <Bar className="aspect-[4/3] w-28" />
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}

import { EventCard, type EventCardData } from '@/components/EventCard';
import { NewEventsNotifier } from '@/components/NewEventsNotifier';
import { API_V1 } from '@/lib/api';
import { formatUtcInstrument, groupFeedByRecency, latestCreatedAt } from '@/lib/time';

async function getEvents() {
  try {
    const res = await fetch(`${API_V1}/events/?scope=week&limit=200`, {
      cache: 'no-store',
    });

    if (!res.ok) {
      throw new Error(`API returned status ${res.status}`);
    }

    return await res.json();
  } catch (error) {
    console.error('Failed to fetch events:', error);
    return null;
  }
}

export default async function Home() {
  const events: EventCardData[] | null = await getEvents();
  const latestCreated = events && events.length > 0 ? latestCreatedAt(events) : '';
  const newestStamp =
    events && events.length > 0
      ? formatUtcInstrument(events[0].event_time ?? events[0].created_at)
      : '';
  const sections =
    events && events.length > 0 ? groupFeedByRecency(events, new Date().toISOString()) : [];

  return (
    <main className="min-h-screen bg-[#070708] text-zinc-100 selection:bg-sky-500/30">
      <a
        href="#latest-developments"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-zinc-100 focus:px-3 focus:py-2 focus:text-sm focus:text-zinc-900"
      >
        Skip to latest developments
      </a>
      <div className="intel-shell py-8 lg:py-10">
        <header className="mb-10 border-b border-white/[0.08] pb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-zinc-400">
            Global AI ecosystem
          </p>
          <h1 className="mt-3 text-[2rem] font-semibold tracking-tight text-white md:text-5xl">
            AI World Intelligence
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-zinc-300">
            Live source-grounded intelligence
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-white/[0.06] pt-5">
            <span className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-400">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" aria-hidden="true" />
              Live
            </span>
            {events ? (
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-zinc-300">
                {events.length} developments
              </span>
            ) : null}
            {newestStamp ? (
              <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-400">
                Updated {newestStamp}
              </span>
            ) : null}
          </div>
        </header>

        <div id="latest-developments" className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-400">
              Latest developments
            </h2>
            <p className="mt-2 text-sm text-zinc-400">
              This week · newest first · times in UTC
            </p>
          </div>
          {latestCreated ? <NewEventsNotifier latestEventTimestamp={latestCreated} /> : null}
        </div>

        {!events ? (
          <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-6 text-center text-red-300">
            <p className="font-semibold">Backend unavailable</p>
            <p className="mt-1 text-sm">Could not connect to the intelligence API.</p>
          </div>
        ) : events.length === 0 ? (
          <div className="rounded-lg border border-white/10 bg-[#111114] p-12 text-center text-zinc-400">
            <p className="text-lg font-medium">No events yet</p>
            <p className="mt-1 text-sm">The ingestion pipeline has not produced any canonical events.</p>
          </div>
        ) : (
          <div className="space-y-12">
            {sections.map((section) => (
              <section key={section.id} aria-labelledby={`section-${section.id}`}>
                <div className="mb-5 border-b border-white/[0.08] pb-3">
                  <h3
                    id={`section-${section.id}`}
                    className="text-[12px] font-semibold uppercase tracking-[0.2em] text-zinc-200"
                  >
                    {section.title}
                  </h3>
                  {section.subtitle ? (
                    <p className="mt-1 text-[12px] tracking-wide text-zinc-500">{section.subtitle}</p>
                  ) : null}
                </div>
                <div className="space-y-8">
                  {section.days.map((day) => (
                    <div key={day.key}>
                      {day.label ? (
                        <h4 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-zinc-400">
                          {day.label}
                        </h4>
                      ) : null}
                      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
                        {day.events.map((event) => (
                          <EventCard key={event.id} event={event} />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

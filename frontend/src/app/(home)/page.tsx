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
    <main className="min-h-screen bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#latest-developments"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to latest developments
      </a>
      <div className="intel-shell py-8 lg:py-10">
        <header className="mb-10 border-b border-line pb-8">
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-muted">
            Global AI ecosystem
          </p>
          <h1 className="mt-3 text-[2rem] font-semibold tracking-tight text-ink md:text-5xl">
            AI World Intelligence
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-secondary">
            Live source-grounded intelligence
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-x-8 gap-y-3 border-t border-line pt-5">
            <span className="inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-success">
              <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden="true" />
              Live
            </span>
            {events ? (
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-secondary">
                {events.length} developments
              </span>
            ) : null}
            {newestStamp ? (
              <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
                Updated {newestStamp}
              </span>
            ) : null}
          </div>
        </header>

        <div id="latest-developments" className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-muted">
              Latest developments
            </h2>
            <p className="mt-2 text-sm text-muted">
              This week · newest first · times in UTC
            </p>
          </div>
          {latestCreated ? <NewEventsNotifier latestEventTimestamp={latestCreated} /> : null}
        </div>

        {!events ? (
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-6 text-center text-danger">
            <p className="font-semibold">Backend unavailable</p>
            <p className="mt-1 text-sm">Could not connect to the intelligence API.</p>
          </div>
        ) : events.length === 0 ? (
          <div className="rounded-lg border border-line bg-surface p-12 text-center text-muted">
            <p className="text-lg font-medium">No events yet</p>
            <p className="mt-1 text-sm">The ingestion pipeline has not produced any canonical events.</p>
          </div>
        ) : (
          <div className="space-y-12">
            {sections.map((section) => (
              <section key={section.id} aria-labelledby={`section-${section.id}`}>
                <div className="mb-5 border-b border-line pb-3">
                  <h3
                    id={`section-${section.id}`}
                    className="text-[12px] font-semibold uppercase tracking-[0.2em] text-secondary"
                  >
                    {section.title}
                  </h3>
                  {section.subtitle ? (
                    <p className="mt-1 text-[12px] tracking-wide text-muted">{section.subtitle}</p>
                  ) : null}
                </div>
                <div className="space-y-8">
                  {section.days.map((day) => (
                    <div key={day.key}>
                      {day.label ? (
                        <h4 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
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

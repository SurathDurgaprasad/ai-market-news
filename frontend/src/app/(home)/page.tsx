import Link from 'next/link';
import { unstable_rethrow } from 'next/navigation';
import { EventCard, type EventCardData } from '@/components/EventCard';
import {
  MarketOverview,
  type IngestionStatus,
  type MarketOverviewData,
} from '@/components/MarketOverview';
import { NewEventsNotifier } from '@/components/NewEventsNotifier';
import { API_V1 } from '@/lib/api';
import { ageHours, formatUtcInstrument, groupFeedByRecency, latestCreatedAt } from '@/lib/time';

// Ingestion runs every few minutes. Beyond this, "Live" would be a claim
// the pipeline cannot back.
const STALE_AFTER_HOURS = 6;

async function getOverview(): Promise<MarketOverviewData | null> {
  try {
    const res = await fetch(`${API_V1}/events/overview`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`API returned status ${res.status}`);
    return await res.json();
  } catch (error) {
    unstable_rethrow(error);
    console.error('Failed to fetch market overview:', error);
    return null;
  }
}

async function getEvents(): Promise<EventCardData[] | null> {
  try {
    const res = await fetch(`${API_V1}/events/?scope=week&limit=250`, {
      cache: 'no-store',
    });
    if (!res.ok) throw new Error(`API returned status ${res.status}`);
    return await res.json();
  } catch (error) {
    unstable_rethrow(error);
    console.error('Failed to fetch events:', error);
    return null;
  }
}

type Freshness = {
  state: 'live' | 'delayed' | 'paused';
  label: string;
  detail: string;
};

function freshness(ingestion: IngestionStatus | undefined, nowMs: number): Freshness | null {
  if (!ingestion) return null;
  const stamp = formatUtcInstrument(ingestion.last_ingested_at);
  const age = ageHours(ingestion.last_ingested_at, nowMs);
  if (!ingestion.llm_available) {
    return {
      state: 'paused',
      label: 'Ingestion paused',
      detail: stamp
        ? `No language model is configured. Showing developments stored up to ${stamp}.`
        : 'No language model is configured. Showing stored developments.',
    };
  }
  const pending = ingestion.pending_enrichment ?? 0;
  const stored = pending > 0
    ? ` ${pending} new ${pending === 1 ? 'article is' : 'articles are'} stored and will appear once enrichment resumes.`
    : '';
  if (ingestion.enrichment_paused) {
    return {
      state: 'paused',
      label: 'Enrichment paused',
      detail: `The language model provider is not responding.${stored}`,
    };
  }
  if (age === null || age > STALE_AFTER_HOURS) {
    return {
      state: 'delayed',
      label: 'Updates delayed',
      detail: (stamp ? `Last new development recorded ${stamp}.` : 'No development has been recorded yet.') + stored,
    };
  }
  return {
    state: 'live',
    label: 'Live',
    detail: stamp ? `Last new development recorded ${stamp}.` : '',
  };
}

const STATE_CLASS: Record<Freshness['state'], { text: string; dot: string }> = {
  live: { text: 'text-success', dot: 'bg-success' },
  delayed: { text: 'text-warning', dot: 'bg-warning' },
  paused: { text: 'text-warning', dot: 'bg-warning' },
};

export default async function Home() {
  const [overview, events] = await Promise.all([getOverview(), getEvents()]);
  // The API's own clock computed the overview windows; the feed groups by the same instant.
  const nowIso = overview?.as_of ?? new Date().toISOString();
  const nowMs = Date.parse(nowIso);
  const status = freshness(overview?.ingestion, nowMs);
  const latestCreated = events && events.length > 0 ? latestCreatedAt(events) : '';
  const sections = events && events.length > 0 ? groupFeedByRecency(events, nowIso) : [];
  const failing = overview?.ingestion?.sources_failing ?? 0;
  const enabled = overview?.ingestion?.sources_enabled ?? 0;

  return (
    <main className="flex-1 bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#latest-developments"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to latest developments
      </a>
      <div className="intel-shell py-6 lg:py-8">
        <div className="mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4 border-b border-line pb-5">
          <div className="min-w-0">
            <h1 className="text-[1.6rem] font-semibold leading-tight tracking-tight text-ink md:text-[1.85rem]">
              What is changing in AI
            </h1>
            <p className="mt-1 text-[13px] text-muted">
              {events ? `${events.length} canonical ${events.length === 1 ? 'development' : 'developments'} this week` : 'This week'}
              {' · '}repeated coverage counts once · times in UTC
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            {status ? (
              <div className="min-w-0" role="status">
                <p className={`inline-flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] ${STATE_CLASS[status.state].text}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${STATE_CLASS[status.state].dot}`} aria-hidden="true" />
                  {status.label}
                </p>
                {status.detail ? <p className="mt-0.5 text-[12px] text-muted">{status.detail}</p> : null}
                {failing > 0 ? (
                  <p className="mt-0.5 text-[12px] text-muted">
                    <Link href="/admin/sources" className="underline decoration-line underline-offset-2 hover:text-ink">
                      {failing} of {enabled} sources failing
                    </Link>
                  </p>
                ) : null}
              </div>
            ) : null}
            {latestCreated ? <NewEventsNotifier latestEventTimestamp={latestCreated} /> : null}
          </div>
        </div>

        {overview ? <MarketOverview data={overview} stale={status?.state !== 'live'} /> : null}

        <div id="latest-developments" className="mb-5 scroll-mt-4 border-b border-line pb-2.5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">This week</p>
          <h2 className="mt-0.5 text-[17px] font-semibold tracking-tight text-ink">Latest developments</h2>
          <p className="mt-0.5 text-[12px] text-muted">
            Newest first. Open a card for evidence and coverage; the source link opens the original.
          </p>
        </div>

        {!events ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-6 text-center text-danger" role="alert">
            <p className="font-semibold">Intelligence API unavailable</p>
            <p className="mt-1 text-sm">The feed could not be loaded. Try again shortly.</p>
          </div>
        ) : events.length === 0 ? (
          <div className="rounded-md border border-line bg-surface p-10 text-center text-muted">
            <p className="text-base font-medium text-secondary">No developments this week yet</p>
            <p className="mt-1 text-sm">New canonical events appear here as sources are ingested.</p>
          </div>
        ) : (
          <div className="space-y-10">
            {sections.map((section) => (
              <section key={section.id} aria-labelledby={`section-${section.id}`}>
                <div className="mb-4 flex flex-wrap items-baseline gap-x-3">
                  <h3
                    id={`section-${section.id}`}
                    className="text-[12px] font-semibold uppercase tracking-[0.18em] text-secondary"
                  >
                    {section.title}
                  </h3>
                  {section.subtitle ? (
                    <p className="text-[12px] tracking-wide text-muted">{section.subtitle}</p>
                  ) : null}
                </div>
                <div className="space-y-7">
                  {section.days.map((day) => (
                    <div key={day.key}>
                      {day.label ? (
                        <p className="mb-3 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted">
                          {day.label}
                        </p>
                      ) : null}
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                        {day.events.map((event) => (
                          <EventCard key={event.id} event={event} headingLevel="h4" />
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

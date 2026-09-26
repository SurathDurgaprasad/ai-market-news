import Link from 'next/link';
import { unstable_rethrow } from 'next/navigation';
import { EventCard, type EventCardData } from '@/components/EventCard';
import { EventRow } from '@/components/EventRow';
import { SectionHeading } from '@/components/ui';
import {
  MarketOverview,
  MarketRail,
  type IngestionStatus,
  type MarketOverviewData,
} from '@/components/MarketOverview';
import { NewEventsNotifier } from '@/components/NewEventsNotifier';
import { API_V1 } from '@/lib/api';
import {
  ageHours,
  formatUtcInstrument,
  formatUtcWeekday,
  groupFeedByRecency,
  latestCreatedAt,
} from '@/lib/time';

// Ingestion runs every few minutes. Beyond this, "Live" would be a claim
// the pipeline cannot back.
const STALE_AFTER_HOURS = 6;
// Significant and Major developments get a full card; the rest form the dense stream.
const CARD_MIN_IMPORTANCE = 70;

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
  state: 'live' | 'delayed' | 'paused' | 'offline';
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
  offline: { text: 'text-danger', dot: 'bg-danger' },
};

// The overview carries ingestion state; without it the page must still say so.
const OFFLINE: Freshness = {
  state: 'offline',
  label: 'API unreachable',
  detail: 'Ingestion status and developments cannot be loaded right now.',
};

export default async function Home() {
  const [overview, events] = await Promise.all([getOverview(), getEvents()]);
  // The API's own clock computed the overview windows; the feed groups by the same instant.
  const nowIso = overview?.as_of ?? new Date().toISOString();
  const nowMs = Date.parse(nowIso);
  const status = overview ? freshness(overview.ingestion, nowMs) : OFFLINE;
  const latestCreated = events && events.length > 0 ? latestCreatedAt(events) : '';
  const sections = events && events.length > 0 ? groupFeedByRecency(events, nowIso) : [];
  const failing = overview?.ingestion?.sources_failing ?? 0;
  const enabled = overview?.ingestion?.sources_enabled ?? 0;
  const today = formatUtcWeekday(nowIso).replace(' · ', ', ');

  return (
    <main className="flex-1 bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#latest-developments"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to latest developments
      </a>
      <div className="intel-shell pb-6 pt-7 lg:pt-9">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
          <div className="min-w-0">
            {today ? <p className="intel-kicker">{today}</p> : null}
            <h1 className="font-display mt-1.5 text-[2.2rem] font-semibold leading-[1.02] text-ink md:text-[2.9rem]">
              What&apos;s happening in AI
            </h1>
            <p className="tabular mt-2 text-[13.5px] text-muted">
              {events ? `${events.length} ${events.length === 1 ? 'development' : 'developments'} this week` : 'This week'}
              {' · '}repeated coverage counts once · times in UTC
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3 md:ml-auto">
            {latestCreated ? <NewEventsNotifier latestEventTimestamp={latestCreated} /> : null}
            {status ? (
              <div className="min-w-0 max-w-[46ch] md:text-right" role="status">
                <p className={`inline-flex items-center gap-2 text-[12px] font-semibold ${STATE_CLASS[status.state].text}`}>
                  <span className={`h-2 w-2 rounded-full ${STATE_CLASS[status.state].dot}`} aria-hidden="true" />
                  {status.label}
                </p>
                {status.detail ? <p className="mt-0.5 text-[12px] leading-snug text-muted text-balance">{status.detail}</p> : null}
                {failing > 0 ? (
                  <p className="mt-0.5 text-[12px] text-muted">
                    <Link href="/admin/sources" className="underline decoration-line underline-offset-2 hover:text-ink">
                      {failing} of {enabled} sources failing
                    </Link>
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>

        {overview ? <MarketOverview data={overview} stale={status?.state !== 'live'} /> : null}

        <div className="mt-14 grid grid-cols-1 gap-x-12 gap-y-12 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
          <div id="latest-developments" className="min-w-0 scroll-mt-20">
            <SectionHeading
              id="latest-heading"
              kicker="This week"
              title="Latest developments"
              note="Newest first. Significant developments as cards, the rest as a compact list. The source link opens the original."
            />

            {!events ? (
              <div className="rounded-md border border-danger/40 bg-danger/10 p-6 text-center text-danger" role="alert">
                <p className="font-semibold">News service unavailable</p>
                <p className="mt-1 text-sm">The feed could not be loaded. Try again shortly.</p>
              </div>
            ) : events.length === 0 ? (
              <div className="rounded-md border border-line bg-surface p-10 text-center text-muted">
                <p className="text-base font-medium text-secondary">No developments this week yet</p>
                <p className="mt-1 text-sm">New developments appear here as sources are read.</p>
              </div>
            ) : (
              <div className="space-y-10">
                {sections.map((section) => (
                  <section key={section.id} aria-labelledby={`section-${section.id}`}>
                    <div className="mb-3 flex flex-wrap items-baseline gap-x-3">
                      <h3
                        id={`section-${section.id}`}
                        className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink"
                      >
                        {section.title}
                      </h3>
                      {section.subtitle ? (
                        <p className="text-[12.5px] text-muted">{section.subtitle}</p>
                      ) : null}
                    </div>
                    <div className="space-y-6">
                      {section.days.map((day) => {
                        const prominent = day.events.filter((event) => event.importance_score >= CARD_MIN_IMPORTANCE);
                        const stream = day.events.filter((event) => event.importance_score < CARD_MIN_IMPORTANCE);
                        return (
                          <div key={day.key} className="space-y-3">
                            {day.label ? <p className="intel-kicker">{day.label}</p> : null}
                            {prominent.length > 0 ? (
                              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
                                {prominent.map((event) => (
                                  <EventCard key={event.id} event={event} headingLevel="h4" />
                                ))}
                              </div>
                            ) : null}
                            {stream.length > 0 ? (
                              <ul
                                className="divide-y divide-line border-y border-line"
                                aria-label={`${stream.length} more ${stream.length === 1 ? 'development' : 'developments'}`}
                              >
                                {stream.map((event) => (
                                  <EventRow key={event.id} event={event} />
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        );
                      })}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>

          {/* On narrow screens the rail comes before the long feed, keeping the page's reading order. */}
          {overview ? (
            <aside className="order-first min-w-0 xl:order-none" aria-label="Activity by area and organization">
              <MarketRail data={overview} />
            </aside>
          ) : null}
        </div>
      </div>
    </main>
  );
}

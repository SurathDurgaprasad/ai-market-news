import type { ReactNode } from "react";
import Link from "next/link";
import { EventImage } from "@/components/EventImage";
import { CategoryTag, PublisherCount, SectionHeading } from "@/components/ui";
import { categoryColor } from "@/lib/categories";
import { factualSummary, formatUtcWhen } from "@/lib/time";

export type OverviewCard = {
  id: string;
  headline: string;
  summary: string;
  organization: string;
  category: string;
  event_time: string;
  importance_score: number;
  importance_label: string;
  source_count: number;
  source_label: string;
  source_name?: string;
  has_image?: boolean;
};

export type PulseExample = {
  id: string;
  headline: string;
};

export type ActivityCount = {
  label: string;
  week: number;
  sources?: number;
  recent?: number;
  examples?: PulseExample[];
};

export type TrendActivity = {
  label: string;
  week: number;
  sources: number;
  recent: number;
};

export type PlayerActivity = {
  slug: string;
  name: string;
  week: number;
  substantive: number;
  significant: number;
  sources: number;
  recent?: number;
  categories?: string[];
  latest_headline: string;
  latest_event_id: string;
  latest_time?: string;
  event_ids: string[];
};

export type IngestionStatus = {
  llm_available: boolean;
  last_ingested_at: string | null;
  sources_enabled: number;
  sources_failing: number;
  pending_enrichment?: number;
  enrichment_paused?: boolean;
};

export type MarketOverviewData = {
  as_of: string;
  happening_now: OverviewCard[];
  trending: TrendActivity[];
  biggest: OverviewCard[];
  pulse: ActivityCount[];
  players: PlayerActivity[];
  ingestion?: IngestionStatus;
};

function importanceClass(label: string): string {
  if (label === "Major") return "text-warning";
  if (label === "Significant") return "text-secondary";
  return "text-muted";
}

function countLabel(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

function EmptyNote({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-[var(--radius-card)] border border-dashed border-line px-4 py-5 text-[13px] leading-relaxed text-muted">
      {children}
    </p>
  );
}

/** Importance, provenance and corroboration: one quiet line under a headline. */
function CardMeta({ card, withSource = true }: { card: OverviewCard; withSource?: boolean }) {
  return (
    <p className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[12.5px] text-muted">
      <span className={`font-medium ${importanceClass(card.importance_label)}`}>{card.importance_label}</span>
      {withSource && card.source_label ? (
        <span>
          <span aria-hidden="true">· </span>
          {card.source_label}
          {card.source_name ? `: ${card.source_name}` : ""}
        </span>
      ) : null}
      {card.source_count > 1 ? (
        <span>
          <span aria-hidden="true">· </span>
          <PublisherCount count={card.source_count} />
        </span>
      ) : null}
    </p>
  );
}

function Subject({ card, compact = false }: { card: OverviewCard; compact?: boolean }) {
  return (
    <p className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-0.5 text-[12px]">
      <CategoryTag category={card.category} />
      {card.organization && !compact ? <span className="font-medium text-secondary">{card.organization}</span> : null}
      <time className="tabular text-muted" dateTime={card.event_time}>
        {formatUtcWhen(card.event_time)}
      </time>
    </p>
  );
}

function leadIndex(cards: OverviewCard[]): number {
  let best = 0;
  cards.forEach((card, index) => {
    if (card.importance_score > cards[best].importance_score) best = index;
  });
  return best;
}

/** The one development to read first: highest importance in the last 36 hours. */
function LeadStory({ card }: { card: OverviewCard }) {
  const summary = factualSummary(card.summary);
  return (
    <article className="group relative min-w-0">
      {card.has_image ? (
        <EventImage
          id={card.id}
          size="lead"
          category={card.category}
          priority
          sizes="(min-width: 1280px) 60vw, 100vw"
          className="mb-5 aspect-[2/1] w-full rounded-[var(--radius-card)] border border-line"
        />
      ) : (
        <div className="mb-5 h-1 w-24 rounded-full" style={{ background: categoryColor(card.category) }} aria-hidden="true" />
      )}
      <Subject card={card} />
      <h3 className="font-display mt-2.5 text-[2rem] font-medium leading-[1.08] text-ink md:text-[2.6rem]">
        <Link href={`/events/${card.id}`} className="card-link headline-hover">
          {card.headline}
        </Link>
      </h3>
      {summary ? (
        <p className="mt-3 line-clamp-3 max-w-[70ch] text-[16.5px] leading-relaxed text-secondary">{summary}</p>
      ) : null}
      <div className="mt-3">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function SecondaryStory({ card }: { card: OverviewCard }) {
  return (
    <li className="group relative grid grid-cols-[minmax(0,1fr)_auto] gap-x-5 py-4 first:pt-0">
      <div className="min-w-0">
        <Subject card={card} />
        <h3 className="font-display mt-1.5 line-clamp-3 text-[1.3rem] font-medium leading-[1.2] text-ink">
          <Link href={`/events/${card.id}`} className="card-link headline-hover">
            {card.headline}
          </Link>
        </h3>
        <div className="mt-1.5">
          <CardMeta card={card} withSource={false} />
        </div>
      </div>
      {card.has_image ? (
        <EventImage
          id={card.id}
          size="thumb"
          category={card.category}
          className="mt-0.5 aspect-[4/3] w-28 rounded-[4px] border border-line xl:w-36"
        />
      ) : null}
    </li>
  );
}

function BiggestCard({ card }: { card: OverviewCard }) {
  return (
    <article className="group relative flex min-w-0 flex-col">
      {card.has_image ? (
        <EventImage
          id={card.id}
          size="card"
          category={card.category}
          sizes="(min-width: 1280px) 22vw, (min-width: 768px) 45vw, 100vw"
          className="mb-3.5 aspect-[16/9] w-full rounded-[var(--radius-card)] border border-line"
        />
      ) : (
        <div
          className="image-frame mb-3.5 flex aspect-[16/9] w-full items-end rounded-[var(--radius-card)] border border-line p-4"
          style={{ ["--plate" as string]: categoryColor(card.category) }}
          aria-hidden="true"
        >
          <span className="font-display text-[1.6rem] italic leading-none" style={{ color: categoryColor(card.category) }}>
            {card.category || card.organization || "AI"}
          </span>
        </div>
      )}
      <Subject card={card} compact />
      <h3 className="font-display mt-1.5 line-clamp-3 text-[1.3rem] font-medium leading-[1.2] text-ink">
        <Link href={`/events/${card.id}`} className="card-link headline-hover">
          {card.headline}
        </Link>
      </h3>
      <div className="mt-auto pt-2">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

// Trending is about the last 36 hours, so that count leads; the week gives scale.
function TrendingStrip({ rows, quietReason }: { rows: TrendActivity[]; quietReason: string }) {
  return (
    <section
      aria-labelledby="trending"
      className="flex flex-col gap-3 border-y border-line py-3 xl:flex-row xl:items-center xl:gap-8"
    >
      <div className="flex shrink-0 items-baseline gap-2">
        <h2 id="trending" className="text-[13px] font-semibold text-ink">
          Trending
        </h2>
        <span className="text-[12px] text-muted">last 36 hours</span>
      </div>
      {rows.length > 0 ? (
        <ul className="flex min-w-0 flex-1 flex-wrap gap-x-7 gap-y-2.5">
          {rows.map((row) => {
            const share = row.week > 0 ? Math.round((row.recent / row.week) * 100) : 0;
            return (
              <li key={row.label} className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-0.5">
                <CategoryTag category={row.label} className="text-[11.5px]" />
                <span className="tabular text-[13px] font-semibold text-ink">{row.recent} new</span>
                <span
                  className="h-[3px] w-10 overflow-hidden rounded-full bg-elevated"
                  role="img"
                  aria-label={`${share}% of this week's ${row.label} developments arrived in the last 36 hours`}
                >
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${Math.max(8, share)}%`, background: categoryColor(row.label) }}
                  />
                </span>
                <span className="tabular text-[12px] text-muted">
                  {row.week} this week · {countLabel(row.sources, "publisher", "publishers")}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">No category has recent activity from more than one publisher.{quietReason}</p>
      )}
      <details className="shrink-0 text-[12px] text-muted">
        <summary className="w-fit cursor-pointer hover:text-ink">How this is ordered</summary>
        <p className="mt-1.5 max-w-[42ch] leading-relaxed">
          Areas with new developments in the last 36 hours and more than one publisher this week. Accelerating
          areas, with 40% or more of the week&apos;s developments in the last 36 hours, come first. Repeated
          coverage of one development counts once.
        </p>
      </details>
    </section>
  );
}

function PulseList({ rows }: { rows: ActivityCount[] }) {
  const max = Math.max(1, ...rows.map((row) => row.week));
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => {
        const example = row.examples?.[0];
        return (
          <li key={row.label} className="py-2.5">
            <div className="flex items-baseline justify-between gap-3">
              <CategoryTag category={row.label} className="text-[11.5px]" />
              <span className="tabular text-[12px] text-muted">
                <span className="text-[15px] font-semibold text-ink">{row.week}</span>
                {(row.recent ?? 0) > 0 ? ` · ${row.recent} in 36h` : ""}
              </span>
            </div>
            <div className="mt-1.5 h-[3px] w-full rounded-full bg-elevated" aria-hidden="true">
              <div
                className="h-full rounded-full opacity-80"
                style={{ width: `${Math.max(4, Math.round((row.week / max) * 100))}%`, background: categoryColor(row.label) }}
              />
            </div>
            {example ? (
              <Link
                href={`/events/${example.id}`}
                className="mt-1.5 line-clamp-1 block text-[12.5px] leading-snug text-muted hover:text-ink"
              >
                {example.headline}
              </Link>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function PlayersList({ players }: { players: PlayerActivity[] }) {
  const max = Math.max(1, ...players.map((player) => player.week));
  return (
    <ul className="divide-y divide-line">
      {players.map((player) => {
        const total = Math.round((player.week / max) * 100);
        const substantive = player.week > 0 ? Math.round((player.substantive / player.week) * 100) : 0;
        return (
          <li key={player.slug} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <Link href={`/players/${player.slug}`} className="text-[14.5px] font-semibold text-ink hover:text-accent">
                {player.name}
              </Link>
              <span className="tabular text-[12px] text-muted">
                {countLabel(player.week, "development", "developments")}
              </span>
            </div>
            <div
              className="mt-1.5 h-[5px] w-full rounded-full bg-elevated"
              role="img"
              aria-label={`${player.week} developments this week, ${player.substantive} substantive`}
            >
              <div className="flex h-full overflow-hidden rounded-full bg-line-strong" style={{ width: `${Math.max(4, total)}%` }}>
                <div className="h-full bg-accent" style={{ width: `${substantive}%` }} />
              </div>
            </div>
            <p className="tabular mt-1 text-[12px] text-muted">
              <span className="text-secondary">{player.substantive} substantive</span>
              {(player.recent ?? 0) > 0 ? ` · ${player.recent} in the last 36h` : ""}
              {player.categories && player.categories.length > 0 ? ` · ${player.categories.join(", ")}` : ""}
            </p>
            <Link
              href={`/events/${player.latest_event_id}`}
              className="mt-1 line-clamp-1 block text-[13px] leading-snug text-secondary hover:text-ink"
            >
              <span className="text-muted">Latest: </span>
              {player.latest_headline}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** Now, Trending and Biggest: the top of the homepage. */
export function MarketOverview({
  data,
  stale = false,
}: {
  data: MarketOverviewData;
  stale?: boolean;
}) {
  const happening = data.happening_now ?? [];
  const trending = data.trending ?? [];
  const biggest = data.biggest ?? [];
  const hasAnything = happening.length > 0 || trending.length > 0 || biggest.length > 0;
  if (!hasAnything) return null;

  const quietReason = stale ? " Ingestion is not current, so recent activity may be missing." : "";
  const lead = happening.length > 0 ? leadIndex(happening) : -1;
  const secondary = happening.filter((_card, index) => index !== lead).slice(0, 4);

  return (
    <div className="space-y-10">
      <TrendingStrip rows={trending} quietReason={quietReason} />

      <section aria-labelledby="happening-now">
        <SectionHeading
          id="happening-now"
          kicker="Last 36 hours"
          title="What's happening now"
          ruled={false}
        />
        {happening.length > 0 ? (
          <div className="grid grid-cols-1 gap-x-10 gap-y-8 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <LeadStory card={happening[lead]} />
            </div>
            {secondary.length > 0 ? (
              <ol className="divide-y divide-line lg:col-span-5 lg:border-l lg:border-line lg:pl-10">
                {secondary.map((card) => (
                  <SecondaryStory key={card.id} card={card} />
                ))}
              </ol>
            ) : null}
          </div>
        ) : (
          <EmptyNote>
            No significant development in the last 36 hours.{quietReason} This week&apos;s biggest developments are
            below.
          </EmptyNote>
        )}
      </section>

      {biggest.length > 0 ? (
        <section aria-labelledby="biggest">
          <SectionHeading
            id="biggest"
            kicker="This week"
            title="Biggest AI developments"
            note="Direct developments, ranked by importance and source quality."
          />
          <div className="grid grid-cols-1 gap-x-6 gap-y-9 sm:grid-cols-2 xl:grid-cols-4">
            {biggest.map((card) => (
              <BiggestCard key={card.id} card={card} />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

/** Market pulse and players: the rail beside the latest developments. */
export function MarketRail({ data }: { data: MarketOverviewData }) {
  const pulse = data.pulse ?? [];
  const players = data.players ?? [];
  if (pulse.length === 0 && players.length === 0) return null;
  return (
    <div className="grid grid-cols-1 gap-x-12 gap-y-10 md:grid-cols-2 xl:grid-cols-1">
      {pulse.length > 0 ? (
        <section aria-labelledby="market-pulse">
          <SectionHeading
            id="market-pulse"
            kicker="This week"
            title="AI market pulse"
            note="Developments per area. Repeated coverage counts once; developments outside these areas are not counted."
          />
          <PulseList rows={pulse} />
        </section>
      ) : null}
      {players.length > 0 ? (
        <section aria-labelledby="players">
          <SectionHeading
            id="players"
            kicker="This week"
            title="Major AI players"
            note="Developments naming each organization. The filled part is substantive work, not discussion or customer stories. Not a ranking."
          />
          <PlayersList players={players} />
        </section>
      ) : null}
    </div>
  );
}

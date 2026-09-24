import type { ReactNode } from "react";
import Link from "next/link";
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

function SectionHeading({
  id,
  kicker,
  title,
  note,
}: {
  id: string;
  kicker: string;
  title: string;
  note?: string;
}) {
  return (
    <div className="mb-1 border-b border-line pb-2.5">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{kicker}</p>
      <h2 id={id} className="mt-0.5 scroll-mt-4 text-[17px] font-semibold tracking-tight text-ink">
        {title}
      </h2>
      {note ? <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{note}</p> : null}
    </div>
  );
}

function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="py-4 text-[13px] leading-relaxed text-muted">{children}</p>;
}

function CardMeta({ card }: { card: OverviewCard }) {
  return (
    <p className="text-[12px] text-muted">
      <span className={importanceClass(card.importance_label)}>{card.importance_label}</span>
      {card.source_label ? (
        <span>
          {" · "}
          {card.source_label}
          {card.source_name ? `: ${card.source_name}` : ""}
        </span>
      ) : null}
      {card.source_count > 1 ? <span> · {countLabel(card.source_count, "source", "sources")}</span> : null}
    </p>
  );
}

function subjectLine(card: OverviewCard): string {
  return [card.organization, card.category].filter(Boolean).join(" · ");
}

function HappeningCard({ card }: { card: OverviewCard }) {
  const summary = factualSummary(card.summary);
  return (
    <article className="border-b border-line py-3.5 last:border-b-0">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <p className="text-[12px] font-medium text-secondary">{subjectLine(card)}</p>
        <time className="text-[11px] tabular-nums tracking-wide text-muted" dateTime={card.event_time}>
          {formatUtcWhen(card.event_time)}
        </time>
      </div>
      <h3 className="text-[1.05rem] font-medium leading-snug tracking-tight text-ink">
        <Link href={`/events/${card.id}`} className="hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      {summary ? (
        <p className="mt-1.5 line-clamp-2 text-[14px] leading-relaxed text-muted">{summary}</p>
      ) : null}
      <div className="mt-1.5">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function BiggestCard({ card }: { card: OverviewCard }) {
  return (
    <article className="border-b border-line py-3.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <p className="text-[12px] font-medium text-secondary">{subjectLine(card)}</p>
        <time className="text-[11px] tabular-nums tracking-wide text-muted" dateTime={card.event_time}>
          {formatUtcWhen(card.event_time)}
        </time>
      </div>
      <h3 className="mt-1 text-[1rem] font-medium leading-snug text-ink">
        <Link href={`/events/${card.id}`} className="hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      <div className="mt-1.5">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function evidenceLine(week: number, sources: number, recent?: number): string {
  const parts = [
    `${week} ${week === 1 ? "development" : "developments"}`,
    countLabel(sources, "source", "sources"),
  ];
  if ((recent ?? 0) > 0) {
    parts.push(`${recent} in 36h`);
  }
  return parts.join(" · ");
}

function TrendList({ rows }: { rows: TrendActivity[] }) {
  return (
    <ul>
      {rows.map((row) => (
        <li key={row.label} className="flex items-baseline justify-between gap-3 border-b border-line py-2.5 last:border-b-0">
          <span className="text-[13px] font-medium text-ink">{row.label}</span>
          <span className="text-right text-[12px] tabular-nums text-secondary">
            {evidenceLine(row.week, row.sources, row.recent)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function PulseList({ rows }: { rows: ActivityCount[] }) {
  const max = Math.max(1, ...rows.map((row) => row.week));
  return (
    <ul>
      {rows.map((row) => (
        <li key={row.label} className="border-b border-line py-2.5 last:border-b-0">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[13px] font-medium text-ink">{row.label}</span>
            <span className="text-right text-[12px] tabular-nums text-secondary">
              {evidenceLine(row.week, row.sources ?? 0, row.recent)}
            </span>
          </div>
          <div className="mt-1.5 h-[3px] w-full rounded-full bg-elevated" aria-hidden="true">
            <div
              className="h-full rounded-full bg-accent/60"
              style={{ width: `${Math.max(4, Math.round((row.week / max) * 100))}%` }}
            />
          </div>
          {row.examples && row.examples.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {row.examples.map((example) => (
                <li key={example.id} className="text-[12px] leading-snug text-muted">
                  <Link href={`/events/${example.id}`} className="hover:text-accent">
                    {example.headline}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function playerStats(player: PlayerActivity): string {
  const parts = [`${player.week} ${player.week === 1 ? "development" : "developments"}`];
  if (player.substantive > 0 && player.substantive < player.week) {
    parts.push(`${player.substantive} substantive`);
  }
  if (player.sources > 0) {
    parts.push(countLabel(player.sources, "source", "sources"));
  }
  if ((player.recent ?? 0) > 0) {
    parts.push(`${player.recent} in 36h`);
  }
  return parts.join(" · ");
}

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
  const pulse = data.pulse ?? [];
  const players = data.players ?? [];
  const hasAnything =
    happening.length > 0 ||
    trending.length > 0 ||
    biggest.length > 0 ||
    pulse.length > 0 ||
    players.length > 0;

  if (!hasAnything) return null;

  const quietReason = stale
    ? " Ingestion is not current, so recent activity may be missing."
    : "";

  return (
    <div className="mb-12 space-y-10">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)] xl:gap-14">
        <div className="min-w-0 space-y-10">
          <section aria-labelledby="happening-now">
            <SectionHeading
              id="happening-now"
              kicker="Now"
              title="What's happening now"
              note="Significant developments from the last 36 hours."
            />
            {happening.length > 0 ? (
              happening.map((card) => <HappeningCard key={card.id} card={card} />)
            ) : (
              <EmptyNote>
                No significant development in the last 36 hours.{quietReason} This week&apos;s
                biggest developments are below.
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
              <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
                {biggest.map((card) => (
                  <BiggestCard key={card.id} card={card} />
                ))}
              </div>
            </section>
          ) : null}
        </div>

        <aside className="min-w-0 space-y-10" aria-label="Activity by category">
          <section aria-labelledby="trending">
            <SectionHeading
              id="trending"
              kicker="Last 36 hours"
              title="Trending"
              note="Categories with distinct developments from more than one publisher."
            />
            {trending.length > 0 ? (
              <TrendList rows={trending} />
            ) : (
              <EmptyNote>No category has recent activity from more than one publisher.{quietReason}</EmptyNote>
            )}
          </section>

          {pulse.length > 0 ? (
            <section aria-labelledby="market-pulse">
              <SectionHeading
                id="market-pulse"
                kicker="This week"
                title="AI market pulse"
                note="Substantive developments per category. Repeated coverage counts once."
              />
              <PulseList rows={pulse} />
            </section>
          ) : null}
        </aside>
      </div>

      {players.length > 0 ? (
        <section aria-labelledby="players">
          <SectionHeading
            id="players"
            kicker="This week"
            title="Major AI players"
            note="Developments attributed to each organization. Substantive excludes discussion, roundups, and customer stories."
          />
          <ul>
            {players.map((player) => (
              <li
                key={player.slug}
                className="grid grid-cols-1 gap-1.5 border-b border-line py-3 last:border-b-0 md:grid-cols-[12rem_minmax(0,1fr)_auto] md:items-baseline md:gap-6"
              >
                <div>
                  <h3 className="text-[14px] font-medium text-ink">
                    <Link href={`/players/${player.slug}`} className="hover:text-accent">
                      {player.name}
                    </Link>
                  </h3>
                  {player.categories && player.categories.length > 0 ? (
                    <p className="mt-0.5 text-[12px] text-muted">{player.categories.join(" · ")}</p>
                  ) : null}
                </div>
                <p className="min-w-0 text-[14px] leading-snug text-secondary">
                  <span className="sr-only">Latest: </span>
                  <Link href={`/events/${player.latest_event_id}`} className="hover:text-accent">
                    {player.latest_headline}
                  </Link>
                </p>
                <div className="text-[12px] tabular-nums text-muted md:text-right">
                  <p>{playerStats(player)}</p>
                  {player.latest_time ? (
                    <p className="mt-0.5 tracking-wide">Latest {formatUtcWhen(player.latest_time)}</p>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

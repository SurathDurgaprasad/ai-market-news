import type { ReactNode } from "react";
import Link from "next/link";
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

/** Importance, provenance and corroboration: one secondary line under every overview headline. */
function CardMeta({ card }: { card: OverviewCard }) {
  return (
    <p className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[12px] text-muted">
      <span className={`font-medium ${importanceClass(card.importance_label)}`}>{card.importance_label}</span>
      {card.source_label ? (
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

function Subject({ card }: { card: OverviewCard }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <p className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-0.5">
        <CategoryTag category={card.category} />
        {card.organization ? <span className="text-[12px] font-medium text-secondary">{card.organization}</span> : null}
      </p>
      <time className="tabular text-[11.5px] tracking-wide text-muted" dateTime={card.event_time}>
        {formatUtcWhen(card.event_time)}
      </time>
    </div>
  );
}

/** The development readers should see first: highest importance in the window. */
function LeadCard({ card }: { card: OverviewCard }) {
  const summary = factualSummary(card.summary);
  return (
    <article
      className="intel-card relative overflow-hidden border px-6 py-5"
      style={{ borderLeft: `3px solid ${categoryColor(card.category)}` }}
    >
      <Subject card={card} />
      <h3 className="mt-2.5 text-[1.55rem] font-semibold leading-[1.25] tracking-[-0.01em] text-ink">
        <Link href={`/events/${card.id}`} className="after:absolute after:inset-0 hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      {summary ? (
        <p className="mt-2.5 line-clamp-3 max-w-[88ch] text-[15px] leading-relaxed text-secondary">{summary}</p>
      ) : null}
      <div className="mt-3.5">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function SupportingCard({ card, wide = false }: { card: OverviewCard; wide?: boolean }) {
  const summary = factualSummary(card.summary);
  return (
    <article className={`intel-card relative flex h-full flex-col border px-4 py-3.5 ${wide ? "md:col-span-2" : ""}`}>
      <Subject card={card} />
      <h3 className="mt-2 text-[1rem] font-semibold leading-snug tracking-tight text-ink">
        <Link href={`/events/${card.id}`} className="after:absolute after:inset-0 hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      {summary ? <p className="mt-1.5 line-clamp-2 text-[13.5px] leading-relaxed text-muted">{summary}</p> : null}
      <div className="mt-auto pt-2.5">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function BiggestCard({ card }: { card: OverviewCard }) {
  return (
    <article className="intel-card relative flex h-full flex-col border px-4 py-3.5">
      <Subject card={card} />
      <h3 className="mt-2 text-[1.05rem] font-semibold leading-snug tracking-tight text-ink">
        <Link href={`/events/${card.id}`} className="after:absolute after:inset-0 hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      <div className="mt-auto pt-2.5">
        <CardMeta card={card} />
      </div>
    </article>
  );
}

function leadIndex(cards: OverviewCard[]): number {
  let best = 0;
  cards.forEach((card, index) => {
    if (card.importance_score > cards[best].importance_score) best = index;
  });
  return best;
}

// Trending is about the last 36 hours, so that count leads; the week gives scale.
function TrendList({ rows }: { rows: TrendActivity[] }) {
  return (
    <ul className="space-y-1">
      {rows.map((row) => {
        const share = row.week > 0 ? Math.round((row.recent / row.week) * 100) : 0;
        return (
          <li key={row.label} className="rounded-[4px] px-1 py-2">
            <div className="flex items-baseline justify-between gap-3">
              <CategoryTag category={row.label} className="text-[12px]" />
              <span className="tabular text-[13px] font-semibold text-ink">
                {row.recent} <span className="font-normal text-muted">new in 36h</span>
              </span>
            </div>
            <div
              className="mt-1.5 h-[3px] w-full rounded-full bg-elevated"
              role="img"
              aria-label={`${share}% of this week's ${row.label} developments arrived in the last 36 hours`}
            >
              <div
                className="h-full rounded-full"
                style={{ width: `${Math.max(4, share)}%`, background: categoryColor(row.label) }}
              />
            </div>
            <p className="tabular mt-1 text-[11.5px] text-muted">
              {`${row.week} this week · ${countLabel(row.sources, "publisher", "publishers")} · ${share}% in 36h`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function PulseList({ rows }: { rows: ActivityCount[] }) {
  const max = Math.max(1, ...rows.map((row) => row.week));
  return (
    <ul className="divide-y divide-line">
      {rows.map((row) => (
        <li key={row.label} className="py-2.5">
          <div className="flex items-baseline justify-between gap-3">
            <CategoryTag category={row.label} className="text-[12px]" />
            <span className="tabular text-right text-[12px] text-muted">
              <span className="text-[15px] font-semibold text-ink">{row.week}</span>{" "}
              {row.week === 1 ? "development" : "developments"}
              {` · ${countLabel(row.sources ?? 0, "publisher", "publishers")}`}
              {(row.recent ?? 0) > 0 ? ` · ${row.recent} in 36h` : ""}
            </span>
          </div>
          <div className="mt-1.5 h-[3px] w-full rounded-full bg-elevated" aria-hidden="true">
            <div
              className="h-full rounded-full opacity-70"
              style={{
                width: `${Math.max(4, Math.round((row.week / max) * 100))}%`,
                background: categoryColor(row.label),
              }}
            />
          </div>
          {row.examples && row.examples.length > 0 ? (
            <ul className="mt-2 space-y-1">
              {row.examples.map((example) => (
                <li key={example.id} className="line-clamp-1 text-[12px] leading-snug text-muted">
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

function Stat({ value, muted = false }: { value: number | string; muted?: boolean }) {
  return <span className={`tabular ${muted ? "text-muted" : "text-ink"}`}>{value}</span>;
}

function PlayersTable({ players }: { players: PlayerActivity[] }) {
  const th = "px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-muted";
  const num = "px-3 py-2.5 text-right text-[13px]";
  return (
    <>
      <div className="hidden overflow-hidden rounded-[var(--radius-card)] border border-line md:block">
        <table className="w-full border-collapse">
          <caption className="sr-only">
            Developments attributed to each organization this week. Not a ranking.
          </caption>
          <thead className="bg-surface">
            <tr className="border-b border-line">
              <th scope="col" className={th}>Organization</th>
              <th scope="col" className={th}>Latest development</th>
              <th scope="col" className={`${th} text-right`}>Developments</th>
              <th scope="col" className={`${th} text-right`}>Substantive</th>
              <th scope="col" className={`${th} text-right`}>Publishers</th>
              <th scope="col" className={`${th} text-right`}>Last 36h</th>
              <th scope="col" className={`${th} text-right`}>Latest</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {players.map((player) => (
              <tr key={player.slug} className="intel-row">
                <th scope="row" className="px-3 py-2.5 text-left align-top">
                  <Link href={`/players/${player.slug}`} className="text-[14px] font-semibold text-ink hover:text-accent">
                    {player.name}
                  </Link>
                  {player.categories && player.categories.length > 0 ? (
                    <p className="mt-0.5 text-[11.5px] font-normal text-muted">{player.categories.join(" · ")}</p>
                  ) : null}
                </th>
                <td className="px-3 py-2.5 align-top text-[13.5px] leading-snug text-secondary">
                  <Link href={`/events/${player.latest_event_id}`} className="line-clamp-2 hover:text-accent">
                    {player.latest_headline}
                  </Link>
                </td>
                <td className={num}><Stat value={player.week} /></td>
                <td className={num}><Stat value={player.substantive} /></td>
                <td className={num}><Stat value={player.sources} muted /></td>
                <td className={num}><Stat value={player.recent ?? 0} muted={!player.recent} /></td>
                <td className="tabular whitespace-nowrap px-3 py-2.5 text-right text-[12px] text-muted">
                  {player.latest_time ? formatUtcWhen(player.latest_time) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="divide-y divide-line md:hidden">
        {players.map((player) => (
          <li key={player.slug} className="py-3">
            <div className="flex items-baseline justify-between gap-3">
              <Link href={`/players/${player.slug}`} className="text-[14px] font-semibold text-ink hover:text-accent">
                {player.name}
              </Link>
              <span className="tabular text-[12px] text-muted">
                {player.week} developments · {player.substantive} substantive
              </span>
            </div>
            <Link
              href={`/events/${player.latest_event_id}`}
              className="mt-1 line-clamp-2 block text-[13.5px] leading-snug text-secondary hover:text-accent"
            >
              {player.latest_headline}
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
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
  const lead = happening.length > 0 ? leadIndex(happening) : -1;
  const supporting = happening.filter((_card, index) => index !== lead);

  return (
    <div className="mb-12 space-y-10">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] xl:grid-cols-[minmax(0,1fr)_420px] xl:gap-10">
        <div className="min-w-0 space-y-10">
          <section aria-labelledby="happening-now">
            <SectionHeading
              id="happening-now"
              kicker="Now · last 36 hours"
              title="What's happening now"
              note="Significant developments from the last 36 hours, most important first."
            />
            {happening.length > 0 ? (
              <div className="space-y-3">
                <LeadCard card={happening[lead]} />
                {supporting.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {supporting.map((card, index) => (
                      <SupportingCard
                        key={card.id}
                        card={card}
                        // An odd last card spans the row instead of leaving a hole in the grid.
                        wide={supporting.length % 2 === 1 && index === supporting.length - 1}
                      />
                    ))}
                  </div>
                ) : null}
              </div>
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
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {biggest.map((card) => (
                  <BiggestCard key={card.id} card={card} />
                ))}
              </div>
            </section>
          ) : null}
        </div>

        <aside className="min-w-0 space-y-10" aria-label="Activity by category">
          <section aria-labelledby="trending" className="rounded-[var(--radius-card)] border border-line bg-surface px-4 pb-3 pt-4">
            <SectionHeading
              id="trending"
              kicker="Signal · last 36 hours"
              title="Trending"
              note="Categories with new developments in the last 36 hours and more than one publisher this week."
            />
            {trending.length > 0 ? (
              <TrendList rows={trending} />
            ) : (
              <EmptyNote>No category has recent activity from more than one publisher.{quietReason}</EmptyNote>
            )}
            <details className="mt-2 text-[12px] text-muted">
              <summary className="w-fit cursor-pointer hover:text-ink">How trending is ordered</summary>
              <p className="mt-1.5 leading-relaxed">
                Accelerating categories, with 40% or more of the week&apos;s developments in the last 36 hours,
                are listed first. Repeated coverage of one development counts once.
              </p>
            </details>
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
            note="Developments attributed to each organization. Substantive excludes discussion, roundups, and customer stories. Not a ranking."
          />
          <PlayersTable players={players} />
        </section>
      ) : null}
    </div>
  );
}

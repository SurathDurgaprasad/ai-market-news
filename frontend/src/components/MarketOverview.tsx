import Link from "next/link";
import { formatUtcInstrument, factualSummary } from "@/lib/time";

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
};

export type ActivityCount = {
  label: string;
  week: number;
  recent?: number;
};

export type TrendActivity = {
  label: string;
  week: number;
  sources: number;
  recent: number;
  activity?: string;
};

export type PlayerActivity = {
  slug: string;
  name: string;
  week: number;
  significant: number;
  sources: number;
  latest_headline: string;
  latest_event_id: string;
  latest_time?: string;
  event_ids: string[];
};

export type MarketOverviewData = {
  as_of: string;
  happening_now: OverviewCard[];
  trending: TrendActivity[];
  biggest: OverviewCard[];
  pulse: ActivityCount[];
  players: PlayerActivity[];
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
    <div className="mb-4 border-b border-line pb-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{kicker}</p>
      <h2 id={id} className="mt-1 text-lg font-semibold tracking-tight text-ink">
        {title}
      </h2>
      {note ? <p className="mt-1 text-[13px] text-muted">{note}</p> : null}
    </div>
  );
}

function HappeningCard({ card }: { card: OverviewCard }) {
  const summary = factualSummary(card.summary);
  const stamp = formatUtcInstrument(card.event_time);
  const meta = [card.organization, card.category].filter(Boolean).join(" · ");

  return (
    <article className="border-b border-line py-4 last:border-b-0">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-[12px] text-secondary">{meta}</p>
        <time className="text-[11px] tracking-wide text-muted" dateTime={card.event_time}>
          {stamp}
        </time>
      </div>
      <h3 className="text-[1.05rem] font-medium leading-snug tracking-tight text-ink">
        <Link href={`/events/${card.id}`} className="hover:text-accent">
          {card.headline}
        </Link>
      </h3>
      {summary ? (
        <p className="mt-2 line-clamp-3 text-[14px] leading-relaxed text-muted">{summary}</p>
      ) : null}
      <p className="mt-2 text-[12px] text-muted">
        <span className={importanceClass(card.importance_label)}>{card.importance_label}</span>
        {card.source_count > 0 ? (
          <span> · {countLabel(card.source_count, "source", "sources")}</span>
        ) : null}
        {card.source_label ? <span> · {card.source_label}</span> : null}
      </p>
    </article>
  );
}

function CountTable({
  rows,
  caption,
}: {
  rows: ActivityCount[];
  caption: string;
}) {
  const showRecent = rows.some((row) => (row.recent ?? 0) > 0);
  return (
    <table className="w-full text-left text-[13px]">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
          <th className="py-2 pr-3 font-semibold">Topic</th>
          {showRecent ? <th className="py-2 pr-3 text-right font-semibold">24h</th> : null}
          <th className="py-2 text-right font-semibold">This week</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label} className="border-b border-line/70 last:border-b-0">
            <th className="py-2.5 pr-3 font-medium text-ink" scope="row">
              {row.label}
            </th>
            {showRecent ? (
              <td className="py-2.5 pr-3 text-right tabular-nums text-secondary">{row.recent ?? 0}</td>
            ) : null}
            <td className="py-2.5 text-right tabular-nums text-secondary">{row.week}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TrendList({ rows }: { rows: TrendActivity[] }) {
  return (
    <div>
      {rows.map((row) => {
        const sources = countLabel(row.sources, "independent source", "independent sources");
        return (
          <article key={row.label} className="border-b border-line py-3 last:border-b-0">
            <h3 className="text-[12px] font-semibold uppercase tracking-[0.16em] text-ink">{row.label}</h3>
            <p className="mt-1 text-[13px] text-secondary">
              {row.week} developments this week · {sources}
            </p>
            {row.activity ? (
              <p className="mt-1 text-[12px] text-muted">Recent activity: {row.activity}</p>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}

function playerStats(player: PlayerActivity): string {
  const parts = [`${player.week} ${player.week === 1 ? "development" : "developments"}`];
  if (player.significant > 0) {
    parts.push(`${player.significant} significant`);
  }
  if (player.sources > 0) {
    parts.push(countLabel(player.sources, "source", "sources"));
  }
  return parts.join(" · ");
}

export function MarketOverview({ data }: { data: MarketOverviewData }) {
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

  return (
    <div className="mb-14 space-y-12">
      {happening.length > 0 ? (
        <section aria-labelledby="happening-now">
          <SectionHeading
            id="happening-now"
            kicker="Now"
            title="What's happening now"
            note="Most meaningful developments in the last 36 hours. Times in UTC."
          />
          <div>
            {happening.map((card) => (
              <HappeningCard key={card.id} card={card} />
            ))}
          </div>
        </section>
      ) : null}

      {trending.length > 0 || pulse.length > 0 ? (
        <div className="grid grid-cols-1 gap-10 lg:grid-cols-2">
          {trending.length > 0 ? (
            <section aria-labelledby="trending">
              <SectionHeading
                id="trending"
                kicker="This week"
                title="Trending"
                note="Categories with recent activity from more than one publisher."
              />
              <TrendList rows={trending} />
            </section>
          ) : null}
          {pulse.length > 0 ? (
            <section aria-labelledby="market-pulse">
              <SectionHeading
                id="market-pulse"
                kicker="This week"
                title="AI market pulse"
                note="This week, Monday–Sunday UTC. A 24h count appears only when that window has events."
              />
              <CountTable rows={pulse} caption="Activity by category" />
            </section>
          ) : null}
        </div>
      ) : null}

      {biggest.length > 0 ? (
        <section aria-labelledby="biggest">
          <SectionHeading
            id="biggest"
            kicker="This week"
            title="Biggest AI developments"
            note="Direct developments this week, by importance and source quality."
          />
          <div className="grid grid-cols-1 gap-x-8 md:grid-cols-2">
            {biggest.map((card) => (
              <article key={card.id} className="border-b border-line py-4">
                <p className="text-[12px] text-secondary">
                  {[card.organization, card.category].filter(Boolean).join(" · ")}
                </p>
                <h3 className="mt-1 text-[1rem] font-medium leading-snug text-ink">
                  <Link href={`/events/${card.id}`} className="hover:text-accent">
                    {card.headline}
                  </Link>
                </h3>
                <p className="mt-2 text-[12px] text-muted">
                  <span className={importanceClass(card.importance_label)}>{card.importance_label}</span>
                  {card.source_label ? <span> · {card.source_label}</span> : null}
                  <span> · {formatUtcInstrument(card.event_time)}</span>
                </p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {players.length > 0 ? (
        <section aria-labelledby="players">
          <SectionHeading
            id="players"
            kicker="This week"
            title="Major AI players"
            note="Organizations with at least one development this week."
          />
          <div>
            {players.map((player) => (
              <article key={player.slug} className="grid grid-cols-1 gap-2 border-b border-line py-4 md:grid-cols-[11rem_1fr_auto] md:items-baseline md:gap-6">
                <h3 className="text-[15px] font-medium text-ink">
                  <Link href={`/players/${player.slug}`} className="hover:text-accent">
                    {player.name}
                  </Link>
                </h3>
                <p className="min-w-0 text-[14px] leading-snug text-secondary">
                  <Link href={`/events/${player.latest_event_id}`} className="hover:text-accent">
                    {player.latest_headline}
                  </Link>
                </p>
                <div className="text-[12px] tabular-nums text-muted md:text-right">
                  <p>{playerStats(player)}</p>
                  {player.latest_time ? (
                    <p className="mt-1 tracking-wide">{formatUtcInstrument(player.latest_time)}</p>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

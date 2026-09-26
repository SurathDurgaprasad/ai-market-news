import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";
import { EventCard, type EventCardData } from "@/components/EventCard";
import { EventRow } from "@/components/EventRow";
import type { MarketOverviewData, PlayerActivity } from "@/components/MarketOverview";
import { API_V1 } from "@/lib/api";
import { PLAYER_NAMES, isKnownPlayer } from "@/lib/players";
import { formatUtcWhen } from "@/lib/time";

async function getPlayerEvents(slug: string): Promise<EventCardData[] | null | "missing"> {
  try {
    const res = await fetch(
      `${API_V1}/events/?scope=week&limit=250&player=${encodeURIComponent(slug)}`,
      { cache: "no-store" },
    );
    if (res.status === 404) return "missing";
    if (!res.ok) throw new Error(`API returned status ${res.status}`);
    return await res.json();
  } catch (error) {
    unstable_rethrow(error);
    console.error("Failed to fetch player events:", error);
    return null;
  }
}

async function getPlayerSummary(slug: string): Promise<PlayerActivity | undefined> {
  try {
    const res = await fetch(`${API_V1}/events/overview`, { cache: "no-store" });
    if (!res.ok) return undefined;
    const data: MarketOverviewData = await res.json();
    return (data.players ?? []).find((player) => player.slug === slug);
  } catch (error) {
    unstable_rethrow(error);
    return undefined;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const requested = (await params).slug;
  const name = isKnownPlayer(requested) ? PLAYER_NAMES[requested] : undefined;
  return { title: name ? `${name} this week` : "Player not found" };
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const name = isKnownPlayer(slug) ? PLAYER_NAMES[slug] : undefined;
  if (!name) notFound();
  const [events, summary] = await Promise.all([getPlayerEvents(slug), getPlayerSummary(slug)]);
  if (events === "missing") notFound();

  const stats = summary
    ? [
        `${summary.week} ${summary.week === 1 ? "development" : "developments"}`,
        `${summary.substantive} substantive`,
        `${summary.sources} ${summary.sources === 1 ? "publisher" : "publishers"}`,
      ]
    : [];

  return (
    <main className="flex-1 bg-canvas text-ink selection:bg-accent/30">
      <div className="intel-shell py-7 lg:py-9">
        <nav className="mb-7" aria-label="Breadcrumb">
          <Link href="/#players" className="text-[13px] font-medium text-secondary hover:text-ink">
            ← Major AI players
          </Link>
        </nav>
        <header className="mb-8 border-b border-line pb-6">
          <p className="intel-kicker">This week</p>
          <h1 className="font-display mt-1.5 text-[2.4rem] font-semibold leading-none text-ink md:text-[2.9rem]">{name}</h1>
          <p className="mt-2.5 max-w-[80ch] text-[13.5px] text-muted">
            Developments published by {name} or naming it in both the headline and the extracted entities.
          </p>
          {stats.length > 0 ? (
            <p className="mt-3 text-[14px] tabular-nums text-secondary">
              {stats.join(" · ")}
              {summary?.categories && summary.categories.length > 0
                ? ` · mostly ${summary.categories.join(" and ")}`
                : ""}
              {summary?.latest_time ? ` · latest ${formatUtcWhen(summary.latest_time)}` : ""}
            </p>
          ) : null}
        </header>

        {!events ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-6 text-center text-danger" role="alert">
            <p className="font-semibold">News service unavailable</p>
            <p className="mt-1 text-sm">Developments for {name} could not be loaded.</p>
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted">No developments attributed to {name} this week.</p>
        ) : (
          <div className="space-y-6">
            {events.some((event) => event.importance_score >= 70) ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {events
                  .filter((event) => event.importance_score >= 70)
                  .map((event) => (
                    <EventCard key={event.id} event={event} headingLevel="h2" withDate />
                  ))}
              </div>
            ) : null}
            {events.some((event) => event.importance_score < 70) ? (
              <ul className="divide-y divide-line border-y border-line">
                {events
                  .filter((event) => event.importance_score < 70)
                  .map((event) => (
                    <EventRow key={event.id} event={event} withDate headingLevel="h2" />
                  ))}
              </ul>
            ) : null}
          </div>
        )}
      </div>
    </main>
  );
}

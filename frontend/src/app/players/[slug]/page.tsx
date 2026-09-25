import type { Metadata } from "next";
import Link from "next/link";
import { notFound, unstable_rethrow } from "next/navigation";
import { EventCard, type EventCardData } from "@/components/EventCard";
import type { MarketOverviewData, PlayerActivity } from "@/components/MarketOverview";
import { API_V1 } from "@/lib/api";
import { formatUtcWhen } from "@/lib/time";

// Mirrors backend app/core/market.py PLAYERS. The API rejects unknown slugs.
const PLAYER_NAMES: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google / DeepMind",
  microsoft: "Microsoft",
  meta: "Meta",
  nvidia: "NVIDIA",
  xai: "xAI",
  amazon: "Amazon",
  alibaba: "Alibaba / Qwen",
  mistral: "Mistral",
  huggingface: "Hugging Face",
};

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
  const name = PLAYER_NAMES[(await params).slug];
  return { title: name ? `${name} this week` : "Player not found" };
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const name = PLAYER_NAMES[slug];
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
      <div className="intel-shell py-6 lg:py-8">
        <nav className="mb-6" aria-label="Breadcrumb">
          <Link href="/#players" className="text-[13px] font-medium text-secondary hover:text-ink">
            ← Major AI players
          </Link>
        </nav>
        <header className="mb-8 border-b border-line pb-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">This week</p>
          <h1 className="mt-1 text-[1.75rem] font-semibold tracking-tight text-ink">{name}</h1>
          <p className="mt-1 text-[13px] text-muted">
            Developments published by {name} or naming it in both the headline and the extracted entities.
          </p>
          {stats.length > 0 ? (
            <p className="mt-3 text-[13px] tabular-nums text-secondary">
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
            <p className="font-semibold">Intelligence API unavailable</p>
            <p className="mt-1 text-sm">Developments for {name} could not be loaded.</p>
          </div>
        ) : events.length === 0 ? (
          <p className="text-sm text-muted">No developments attributed to {name} this week.</p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {events.map((event) => (
              <EventCard key={event.id} event={event} headingLevel="h2" withDate />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

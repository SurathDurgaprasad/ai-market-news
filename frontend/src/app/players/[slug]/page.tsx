import Link from "next/link";
import { EventCard, type EventCardData } from "@/components/EventCard";
import { API_V1 } from "@/lib/api";

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

async function getPlayerEvents(slug: string): Promise<EventCardData[] | null> {
  try {
    const res = await fetch(
      `${API_V1}/events/?scope=week&limit=200&player=${encodeURIComponent(slug)}`,
      { cache: "no-store" },
    );
    if (!res.ok) throw new Error(`API returned status ${res.status}`);
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch player events:", error);
    return null;
  }
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const name = PLAYER_NAMES[slug] ?? slug;
  const events = await getPlayerEvents(slug);

  return (
    <main className="min-h-screen bg-canvas text-ink selection:bg-accent/30">
      <div className="intel-shell py-8 lg:py-10">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
          This week
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink">{name}</h1>
        <p className="mt-2 text-sm text-muted">Developments linked to this organization.</p>
        <Link href="/" className="mt-4 inline-block text-[13px] text-secondary hover:text-accent">
          ← Back to intelligence
        </Link>

        {!events ? (
          <div className="mt-10 rounded-lg border border-danger/40 bg-danger/10 p-6 text-center text-danger">
            <p className="font-semibold">Backend unavailable</p>
          </div>
        ) : events.length === 0 ? (
          <p className="mt-10 text-sm text-muted">No current-week developments for this organization.</p>
        ) : (
          <div className="mt-10 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
            {events.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}

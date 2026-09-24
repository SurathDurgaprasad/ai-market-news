/**
 * How a source link should be labeled. URLs come from the pipeline only.
 *
 * Tiers from the API:
 * - primary   curated official publisher (a lab's own blog)
 * - research  paper or preprint
 * - origin    the original article behind an aggregator link; its publisher
 *             is known from page evidence but it is not an official source
 * - secondary news coverage
 * - community discussion (Hacker News and similar)
 */

const PAPER_HOST = /arxiv\.org|openreview\.net|aclanthology\.org|nature\.com\/articles|dl\.acm\.org|ieeexplore\.ieee\.org/i;

export type SourceRef = { name: string; url: string; tier: string };

export function evidenceLabel(input: {
  url?: string | null;
  tier?: string | null;
}): string {
  const url = input.url ?? "";
  if (PAPER_HOST.test(url)) return "Research paper";
  const tier = (input.tier ?? "").toLowerCase();
  if (tier === "primary") return "Official source";
  if (tier === "research") return "Research paper";
  if (tier === "origin") return "Original article";
  if (tier === "secondary") return "News coverage";
  if (tier === "community") return "Discussion";
  return "Source";
}

/** The publisher readers should see, and the tier that describes it. */
export function displaySource(event: {
  official_source?: SourceRef | null;
  primary_source?: SourceRef | null;
}): SourceRef | undefined {
  return event.official_source ?? event.primary_source ?? undefined;
}

export function isOfficialTier(tier?: string | null): boolean {
  const value = (tier ?? "").toLowerCase();
  return value === "primary" || value === "research";
}

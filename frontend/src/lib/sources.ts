/**
 * How a source link should be labeled. URLs come from the pipeline only.
 */

const PAPER_HOST = /arxiv\.org|openreview\.net|aclanthology\.org|nature\.com\/articles|dl\.acm\.org|ieeexplore\.ieee\.org/i;

export function evidenceLabel(input: {
  url?: string | null;
  tier?: string | null;
  official?: boolean;
}): string {
  const url = input.url ?? "";
  if (PAPER_HOST.test(url)) return "Research paper";
  if (input.official) return "Official source";
  const tier = (input.tier ?? "").toLowerCase();
  if (tier === "primary" || tier === "research") {
    return tier === "research" ? "Research paper" : "Official source";
  }
  if (tier === "secondary") return "Supporting coverage";
  if (tier === "community") return "Discussion";
  return "Source";
}

/**
 * Category visual language. Categories come from the stored event
 * classification (backend app/core/market.py market_category). Related
 * categories share one desaturated hue family so the palette stays
 * restrained; the label, not the color, carries the meaning.
 */
const FAMILY: Record<string, string> = {
  models: "var(--cat-models)",
  multimodal: "var(--cat-models)",
  research: "var(--cat-research)",
  agents: "var(--cat-agents)",
  coding: "var(--cat-agents)",
  hardware: "var(--cat-hardware)",
  infrastructure: "var(--cat-hardware)",
  robotics: "var(--cat-hardware)",
  security: "var(--cat-security)",
  "open source": "var(--cat-open)",
  policy: "var(--cat-neutral)",
  funding: "var(--cat-neutral)",
  partnerships: "var(--cat-neutral)",
};

export function categoryColor(category?: string | null): string {
  return FAMILY[(category ?? "").trim().toLowerCase()] ?? "var(--cat-neutral)";
}

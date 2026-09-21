/**
 * UTC stamps parsed from the ISO string itself.
 *
 * Do not use `new Date(...)` here: Node and the browser can disagree on naive
 * ISO strings, which hydrates Event Detail with a mismatch and a click-blocking
 * Next.js error overlay.
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function utcParts(value?: string | null) {
  if (!value) return null;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!match) return null;
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) return null;
  return {
    year: match[1],
    month,
    day: match[3],
    hour: match[4],
    minute: match[5],
  };
}

export function formatUtcStamp(value?: string | null): string {
  const parts = utcParts(value);
  if (!parts) return "";
  return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute}`;
}

export function formatUtcDay(value?: string | null): string {
  const parts = utcParts(value);
  if (!parts) return "";
  return `${parts.day} ${parts.month}`;
}

export function formatUtcInstrument(value?: string | null): string {
  const parts = utcParts(value);
  if (!parts) return "";
  return `${parts.day} ${parts.month} · ${parts.hour}:${parts.minute} UTC`;
}

export function formatUtcMeta(value?: string | null): string {
  const parts = utcParts(value);
  if (!parts) return "";
  return `${parts.day} ${parts.month} ${parts.year} · ${parts.hour}:${parts.minute} UTC`;
}

export function factualSummary(value?: string | null): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

export function latestCreatedAt(events: Array<{ created_at?: string | null }>): string {
  return events.reduce((max, event) => {
    const stamp = event.created_at ?? "";
    return stamp > max ? stamp : max;
  }, "");
}

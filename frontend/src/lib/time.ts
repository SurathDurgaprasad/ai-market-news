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

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function utcYmd(value?: string | null): { year: number; month: number; day: number } | null {
  if (!value) return null;
  const match = value.trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year: Number(match[1]), month, day };
}

function utcDayNumber(ymd: { year: number; month: number; day: number }): number {
  return Math.floor(Date.UTC(ymd.year, ymd.month - 1, ymd.day) / 86400000);
}

export function formatUtcClock(value?: string | null): string {
  const parts = utcParts(value);
  if (!parts) return "";
  let hour = Number(parts.hour);
  const suffix = hour >= 12 ? "PM" : "AM";
  hour = hour % 12;
  if (hour === 0) hour = 12;
  return `${hour}:${parts.minute} ${suffix}`;
}

export function formatUtcWeekday(value?: string | null): string {
  const ymd = utcYmd(value);
  if (!ymd) return "";
  const name = WEEKDAYS[new Date(Date.UTC(ymd.year, ymd.month - 1, ymd.day)).getUTCDay()];
  const month = MONTHS[ymd.month - 1];
  return `${name} · ${String(ymd.day)} ${month}`;
}

export interface FeedDay<T> {
  key: string;
  label: string;
  events: T[];
}

export interface FeedSection<T> {
  id: "today" | "yesterday" | "earlier" | "older";
  title: string;
  subtitle: string;
  days: FeedDay<T>[];
}

/**
 * Group an already newest-first list into the current week's reading order.
 * Dates are taken from the ISO string (UTC), not the runtime timezone.
 */
export function groupFeedByRecency<T extends { event_time?: string | null; created_at?: string | null }>(
  events: T[],
  nowIso: string,
): FeedSection<T>[] {
  const now = utcYmd(nowIso);
  const nowNumber = now ? utcDayNumber(now) : null;
  const buckets: Record<FeedSection<T>["id"], T[]> = {
    today: [],
    yesterday: [],
    earlier: [],
    older: [],
  };

  for (const event of events) {
    const stamp = event.event_time || event.created_at || "";
    const ymd = utcYmd(stamp);
    if (!ymd || nowNumber === null) {
      buckets.older.push(event);
      continue;
    }
    const delta = nowNumber - utcDayNumber(ymd);
    if (delta <= 0) buckets.today.push(event);
    else if (delta === 1) buckets.yesterday.push(event);
    else if (delta <= 3) buckets.earlier.push(event);
    else buckets.older.push(event);
  }

  const sections: FeedSection<T>[] = [];

  const pushSingle = (id: "today" | "yesterday", title: string, items: T[]) => {
    if (items.length === 0) return;
    const stamp = items[0].event_time || items[0].created_at || "";
    sections.push({
      id,
      title,
      subtitle: formatUtcWeekday(stamp),
      days: [{ key: id, label: "", events: items }],
    });
  };

  const pushMulti = (id: "earlier" | "older", title: string, items: T[]) => {
    if (items.length === 0) return;
    const days: FeedDay<T>[] = [];
    for (const event of items) {
      const stamp = event.event_time || event.created_at || "";
      const ymd = utcYmd(stamp);
      const key = ymd ? `${ymd.year}-${ymd.month}-${ymd.day}` : "undated";
      const last = days[days.length - 1];
      if (!last || last.key !== key) {
        days.push({ key, label: formatUtcWeekday(stamp) || "Undated", events: [event] });
      } else {
        last.events.push(event);
      }
    }
    sections.push({ id, title, subtitle: "", days });
  };

  pushSingle("today", "Today", buckets.today);
  pushSingle("yesterday", "Yesterday", buckets.yesterday);
  pushMulti("earlier", "Earlier this week", buckets.earlier);
  pushMulti("older", "Older this week", buckets.older);
  return sections;
}

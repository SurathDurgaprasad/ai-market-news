import Link from 'next/link';
import type { EventCardData } from '@/components/EventCard';
import { CategoryTag } from '@/components/ui';
import { importanceMeta } from '@/lib/importance';
import { displaySource, evidenceLabel } from '@/lib/sources';
import { factualSummary, formatUtcCardTime, formatUtcWhen } from '@/lib/time';
import { safeHttpUrl } from '@/lib/urls';

/**
 * One development as a compact row: the dense stream for Notable and Minor
 * developments, so an analyst can review many quickly. Significant and Major
 * developments keep the full card.
 */
export function EventRow({
  event,
  withDate = false,
  headingLevel: Heading = 'h4',
}: {
  event: EventCardData;
  withDate?: boolean;
  headingLevel?: 'h2' | 'h3' | 'h4';
}) {
  const tier = importanceMeta(event.importance_score);
  const source = displaySource(event);
  const sourceHref =
    safeHttpUrl(event.article_url) || safeHttpUrl(source?.url) || safeHttpUrl(event.primary_source?.url);
  const sourceLabel = evidenceLabel({ url: sourceHref, tier: source?.tier });
  const stamp = event.event_time ?? event.created_at;
  const summary = factualSummary(event.short_summary);
  const otherSources = Math.max(0, (event.source_count ?? 1) - 1);

  return (
    <li
      className={`intel-row relative grid gap-x-4 gap-y-1 px-3 py-2.5 ${
        withDate
          ? 'grid-cols-[7.5rem_minmax(0,1fr)] md:grid-cols-[8rem_8.5rem_minmax(0,1fr)_13rem]'
          : 'grid-cols-[4.25rem_minmax(0,1fr)] md:grid-cols-[4.25rem_8.5rem_minmax(0,1fr)_13rem]'
      }`}
    >
      <time className="tabular pt-0.5 text-[12px] text-muted" dateTime={stamp}>
        {withDate ? formatUtcWhen(stamp) : formatUtcCardTime(stamp)}
      </time>
      <div className="hidden pt-0.5 md:block">
        {event.category ? <CategoryTag category={event.category} /> : (
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{tier.label}</span>
        )}
      </div>
      <div className="min-w-0">
        <Heading className="font-display text-[1.05rem] font-medium leading-snug text-ink">
          <Link href={`/events/${event.id}`} className="after:absolute after:inset-0 hover:text-accent">
            {event.headline}
          </Link>
          {event.is_update ? (
            <span className="ml-2 align-middle text-[10.5px] font-semibold uppercase tracking-[0.12em] text-accent">
              Updated
            </span>
          ) : null}
        </Heading>
        {summary ? <p className="mt-0.5 line-clamp-1 text-[13px] text-muted">{summary}</p> : null}
        <p className="mt-0.5 text-[11.5px] text-muted md:hidden">
          {[event.category, tier.label].filter(Boolean).join(' · ')}
        </p>
      </div>
      <div className="col-start-2 min-w-0 text-[12px] md:col-start-auto md:pt-0.5 md:text-right">
        <p className="truncate text-secondary">
          {source?.name ?? 'Source unavailable'}
          {otherSources > 0 ? (
            <span className="text-muted">
              {' '}+{otherSources}
              <span className="sr-only"> more {otherSources === 1 ? 'publisher' : 'publishers'}</span>
            </span>
          ) : null}
        </p>
        {sourceHref ? (
          <a
            href={sourceHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${sourceLabel}: ${source?.name ?? 'source'} (opens in a new tab)`}
            className="relative z-10 text-[11.5px] text-muted hover:text-accent"
          >
            {sourceLabel}
            <span aria-hidden="true"> ↗</span>
          </a>
        ) : null}
      </div>
    </li>
  );
}

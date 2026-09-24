'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { factualSummary, formatUtcCardTime } from '@/lib/time';
import { displaySource, evidenceLabel, type SourceRef } from '@/lib/sources';
import {
  cardImageClass,
  entityPreview,
  importanceMeta,
  shouldShowCardImage,
  type ImageRole,
} from '@/lib/importance';
import { safeHttpUrl } from '@/lib/urls';

export interface EventCardData {
  id: string;
  headline: string;
  short_summary: string;
  importance_score: number;
  created_at: string;
  event_time?: string;
  category?: string;
  entities?: string[];
  primary_source?: SourceRef;
  official_source?: SourceRef;
  ingest_source?: SourceRef;
  image_url?: string;
  image_role?: ImageRole;
  article_url?: string;
}

export const EventCard: React.FC<{ event: EventCardData; headingLevel?: 'h2' | 'h3' | 'h4' }> = ({
  event,
  headingLevel: Heading = 'h3',
}) => {
  const [imageFailed, setImageFailed] = useState(false);
  const tier = importanceMeta(event.importance_score);
  const source = displaySource(event);
  const showImage =
    !imageFailed && shouldShowCardImage(event.image_url, event.image_role, tier.key);
  const safeImageUrl = showImage ? safeHttpUrl(event.image_url, { keepQuery: true }) : undefined;
  const imageClass = cardImageClass(event.image_role, tier.image);
  const sourceHref =
    safeHttpUrl(event.article_url) || safeHttpUrl(source?.url) || safeHttpUrl(event.primary_source?.url);
  const sourceLabel = evidenceLabel({ url: sourceHref, tier: source?.tier });
  const stamp = event.event_time ?? event.created_at;
  const displayTime = formatUtcCardTime(stamp);
  const summary = factualSummary(event.short_summary);
  const entities = entityPreview(event.entities, 3);
  const isMinor = tier.key === 'minor';

  return (
    <article
      className={`intel-card group relative flex h-full flex-col overflow-hidden rounded-md border transition-colors hover:border-muted/60 ${tier.card} ${tier.accent}`}
    >
      <Link
        href={`/events/${event.id}`}
        className="flex min-h-0 flex-1 flex-col rounded-[inherit] focus-visible:outline-offset-[-2px]"
      >
        {safeImageUrl ? (
          <div className={`relative w-full overflow-hidden border-b border-line bg-elevated ${imageClass}`}>
            <img
              src={safeImageUrl}
              alt=""
              loading="lazy"
              decoding="async"
              referrerPolicy="no-referrer"
              className="absolute inset-0 h-full w-full object-cover"
              onError={() => setImageFailed(true)}
            />
          </div>
        ) : null}

        <div className={`flex flex-1 flex-col ${isMinor ? 'px-4 pt-3.5' : 'px-4 pt-4'}`}>
          <div className="mb-2 flex items-baseline justify-between gap-3 text-[11px] font-semibold uppercase tracking-[0.14em]">
            <span className="min-w-0 truncate">
              <span className={tier.badge}>{tier.label}</span>
              {event.category ? <span className="text-muted"> · {event.category}</span> : null}
            </span>
            <time className="shrink-0 font-medium normal-case tracking-wide text-muted" dateTime={stamp}>
              {displayTime}
            </time>
          </div>

          <Heading className={`mb-2 line-clamp-3 font-medium tracking-tight text-ink group-hover:text-accent ${tier.title}`}>
            {event.headline}
          </Heading>

          {summary ? (
            <p
              className={`leading-relaxed text-muted ${
                isMinor ? 'line-clamp-2 text-[13px]' : 'line-clamp-3 text-[14px]'
              }`}
            >
              {summary}
            </p>
          ) : (
            <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-warning">
              Summary unavailable
            </p>
          )}

          {entities.shown.length > 0 ? (
            <p className="mt-3 line-clamp-1 text-[12px] leading-relaxed text-secondary">
              {entities.shown.join(' · ')}
              {entities.remainder > 0 ? ` +${entities.remainder}` : ''}
            </p>
          ) : null}
        </div>
      </Link>

      <div className="mt-3 flex items-center justify-between gap-3 border-t border-line/70 px-4 py-2.5">
        <p className="min-w-0 truncate text-[12px] text-muted">{source?.name ?? 'Source unavailable'}</p>
        {sourceHref ? (
          <a
            href={sourceHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${sourceLabel}: ${source?.name ?? 'source'} (opens in a new tab)`}
            className="shrink-0 text-[12px] text-secondary transition-colors hover:text-accent focus-visible:text-accent"
          >
            {sourceLabel}
            <span aria-hidden="true"> ↗</span>
          </a>
        ) : null}
      </div>
    </article>
  );
};

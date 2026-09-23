'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { factualSummary, formatUtcClock, formatUtcDay } from '@/lib/time';
import { evidenceLabel } from '@/lib/sources';
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
  entities?: string[];
  primary_source?: {
    name: string;
    url: string;
    tier: string;
  };
  official_source?: {
    name: string;
    url: string;
    tier: string;
  };
  ingest_source?: {
    name: string;
    url: string;
    tier: string;
  };
  image_url?: string;
  image_role?: ImageRole;
  article_url?: string;
}

export const EventCard: React.FC<{ event: EventCardData }> = ({ event }) => {
  const [imageFailed, setImageFailed] = useState(false);
  const tier = importanceMeta(event.importance_score);
  const displaySource = event.official_source ?? event.primary_source;
  const showImage =
    !imageFailed &&
    shouldShowCardImage(event.image_url, event.image_role, tier.key);
  const safeImageUrl = showImage ? safeHttpUrl(event.image_url, { keepQuery: true }) : undefined;
  const imageClass = cardImageClass(event.image_role, tier.image);
  const officialHref =
    safeHttpUrl(event.article_url) ||
    safeHttpUrl(displaySource?.url) ||
    safeHttpUrl(event.primary_source?.url);
  const sourceLabel = evidenceLabel({
    url: officialHref,
    tier: displaySource?.tier,
    official: Boolean(event.official_source),
  });
  const displayTime =
    formatUtcClock(event.event_time ?? event.created_at) ||
    formatUtcDay(event.event_time ?? event.created_at);
  const summary = factualSummary(event.short_summary);
  const href = `/events/${event.id}`;
  const entities = entityPreview(event.entities, 3);
  const isMinor = tier.key === 'minor';

  return (
    <article
      className={`intel-card group relative flex h-full flex-col overflow-hidden rounded-lg border bg-[#111114] ${tier.card} ${tier.accent}`}
    >
      <Link
        href={href}
        prefetch
        className="flex min-h-0 flex-1 flex-col rounded-[inherit] focus-visible:outline-offset-[-2px]"
      >
        {safeImageUrl ? (
          <div className={`relative w-full overflow-hidden border-b border-white/[0.06] ${imageClass}`}>
            <img
              src={safeImageUrl}
              alt=""
              role="presentation"
              className="absolute inset-0 h-full w-full object-cover"
              onError={() => setImageFailed(true)}
            />
          </div>
        ) : displaySource && !isMinor ? (
          <div className="flex min-h-[4.75rem] items-center justify-center border-b border-white/[0.06] bg-[#0c0c0e] px-5">
            <p className="text-center text-[11px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
              {displaySource.name}
            </p>
          </div>
        ) : null}

        <div className={`flex flex-1 flex-col ${isMinor ? 'px-4 pt-4' : 'px-5 pt-4'}`}>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <span className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${tier.badge}`}>
              {tier.label}
            </span>
            <time
              className="shrink-0 text-[11px] font-medium tracking-wide text-zinc-400"
              dateTime={event.event_time ?? event.created_at}
            >
              {displayTime}
            </time>
          </div>

          <h3
            className={`mb-2 line-clamp-3 font-medium tracking-tight text-zinc-50 group-hover:text-white ${tier.title}`}
          >
            {event.headline}
          </h3>

          {summary ? (
            <p
              className={`leading-relaxed text-zinc-400 ${
                isMinor ? 'line-clamp-2 text-[13px]' : 'line-clamp-2 text-[14px]'
              }`}
            >
              {summary}
            </p>
          ) : (
            <p className="text-[12px] font-medium uppercase tracking-[0.14em] text-amber-400/80">
              Processing
            </p>
          )}

          {entities.shown.length > 0 ? (
            <p className="mt-3 line-clamp-1 text-[12px] leading-relaxed text-zinc-400">
              {entities.shown.join(' · ')}
              {entities.remainder > 0 ? ` +${entities.remainder}` : ''}
            </p>
          ) : null}

          <p className="mt-auto pt-4 text-[12px] text-zinc-400 transition-colors group-hover:text-zinc-200">
            View event →
          </p>
        </div>
      </Link>

      <div className="flex items-center justify-between gap-3 px-5 pb-4">
        <p className="min-w-0 truncate text-[13px] text-zinc-400">
          {displaySource?.name ?? 'Source unavailable'}
        </p>
        {officialHref ? (
          <a
            href={officialHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`${sourceLabel}: ${displaySource?.name ?? 'source'}`}
            className="shrink-0 text-[13px] text-zinc-300 transition-colors hover:text-sky-300 focus-visible:text-sky-300"
          >
            {sourceLabel}
          </a>
        ) : null}
      </div>
    </article>
  );
};

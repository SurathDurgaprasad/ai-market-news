import React, { cache } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound, redirect, unstable_rethrow } from 'next/navigation';
import { API_V1 } from '@/lib/api';
import { formatCitation } from '@/lib/citations';
import { importanceMeta, type ImageRole } from '@/lib/importance';
import { displaySource, evidenceLabel, isOfficialTier, type SourceRef } from '@/lib/sources';
import { factualSummary, formatUtcMeta, formatUtcWhen, hasClockTime, formatUtcDay } from '@/lib/time';
import { safeHttpUrl } from '@/lib/urls';
import { CategoryTag } from '@/components/ui';
import { EventImage } from '@/components/EventImage';

type LinkedArticle = {
  title: string;
  url: string;
  source_name: string;
  source_tier?: string;
  published_at?: string | null;
  link_type: string;
};

type RelatedEvent = {
  id: string;
  headline: string;
  event_time?: string | null;
  category?: string;
  reason: string;
};

type PreviousVersion = {
  id: string;
  version: number;
  headline: string;
  recorded_at: string;
};

type EventDetail = {
  id: string;
  headline: string;
  short_summary: string;
  what_changed?: string | null;
  importance_score?: number;
  created_at: string;
  event_time?: string | null;
  category?: string;
  primary_source?: SourceRef | null;
  ingest_source?: SourceRef | null;
  official_source?: SourceRef | null;
  citations?: string[];
  image_url?: string | null;
  image_role?: string;
  article_url?: string | null;
  entities?: string[];
  linked_articles?: LinkedArticle[];
  canonical_id?: string | null;
  related?: RelatedEvent[];
  version?: number;
  is_update?: boolean;
  source_count?: number;
  previous_versions?: PreviousVersion[];
};

type Loaded = { kind: 'ok'; event: EventDetail } | { kind: 'missing' } | { kind: 'unavailable' };

const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

// Shared by generateMetadata and the page: one API request per render.
const getEvent = cache(async (id: string): Promise<Loaded> => {
  if (!UUID.test(id)) return { kind: 'missing' };
  try {
    const res = await fetch(`${API_V1}/events/${encodeURIComponent(id)}`, { cache: 'no-store' });
    if (res.status === 404 || res.status === 400) return { kind: 'missing' };
    if (!res.ok) throw new Error(`API returned ${res.status}`);
    return { kind: 'ok', event: await res.json() };
  } catch (error) {
    unstable_rethrow(error);
    console.error('Failed to fetch event detail:', error);
    return { kind: 'unavailable' };
  }
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const loaded = await getEvent((await params).id);
  if (loaded.kind === 'ok') {
    return { title: loaded.event.headline, description: factualSummary(loaded.event.short_summary) || undefined };
  }
  return { title: loaded.kind === 'missing' ? 'Development not found' : 'Development unavailable' };
}

function changePoints(value?: string | null): string[] {
  if (!value) return [];
  return value
    .split('\n')
    .map((line) => line.replace(/^\s*[-•*]\s*/, '').trim())
    .filter(Boolean);
}

function asImageRole(value: unknown): ImageRole | undefined {
  if (value === 'hero' || value === 'source' || value === 'none') return value;
  return undefined;
}

function published(value?: string | null): string {
  if (!value) return '';
  return hasClockTime(value) ? formatUtcMeta(value) : formatUtcDay(value);
}

const OPEN_LABEL: Record<string, string> = {
  'Official source': 'Open official source',
  'Research paper': 'Open paper',
  'Original article': 'Open original article',
  'News coverage': 'Open article',
  Discussion: 'Open discussion',
};

// Long extractions name every person quoted; the first few carry the subject.
const ENTITY_PREVIEW = 10;

function EntityChip({ name }: { name: string }) {
  return <li className="rounded border border-line px-2 py-0.5 text-[13px] text-secondary">{name}</li>;
}

function SideHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{children}</h2>
  );
}

export default async function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const loaded = await getEvent(id);

  if (loaded.kind === 'missing') notFound();
  if (loaded.kind === 'unavailable') {
    return (
      <main className="flex-1 bg-canvas text-ink">
        <div className="intel-shell py-16 text-center" role="alert">
          <h1 className="font-display mb-3 text-[2rem] font-semibold text-ink">Development temporarily unavailable</h1>
          <p className="mb-8 text-muted">The news service could not be reached. Try again shortly.</p>
          <Link href="/" className="text-accent hover:underline">
            ← Back to the homepage
          </Link>
        </div>
      </main>
    );
  }

  const event = loaded.event;
  // A merged duplicate resolves to the canonical event that now holds its evidence.
  if (event.canonical_id && event.canonical_id !== event.id) {
    redirect(`/events/${event.canonical_id}`);
  }

  const source = displaySource(event);
  const sourceHref =
    safeHttpUrl(event.article_url) || safeHttpUrl(source?.url) || safeHttpUrl(event.primary_source?.url);
  const sourceLabel = evidenceLabel({ url: sourceHref, tier: source?.tier });
  const tier = importanceMeta(event.importance_score ?? 0);
  const occurred = event.event_time ?? event.created_at;
  const displayTime = published(occurred);
  const versions = Array.isArray(event.previous_versions) ? event.previous_versions : [];
  const version = event.version ?? 1;
  // Versions recorded only because page chrome changed are not updates.
  const isUpdate = event.is_update === true;
  const updatedAt = isUpdate ? formatUtcMeta(event.created_at) : '';
  // A page edit creates a new version; the development was first recorded with version 1.
  const firstSeen = formatUtcMeta(versions.length > 0 ? versions[versions.length - 1].recorded_at : event.created_at);
  const summary = factualSummary(event.short_summary);
  const imageRole = asImageRole(event.image_role);
  const safeImageUrl =
    imageRole === 'none' ? undefined : safeHttpUrl(event.image_url, { keepQuery: true });
  const citations = Array.isArray(event.citations)
    ? event.citations.map((item) => formatCitation(item)).filter(Boolean)
    : [];
  const keyChanges = changePoints(event.what_changed);
  const entities = Array.isArray(event.entities)
    ? event.entities.map((item) => item.trim()).filter(Boolean)
    : [];
  const linked = Array.isArray(event.linked_articles) ? event.linked_articles : [];
  const supporting = linked.filter((article) => article.link_type !== 'primary');
  const publishers = new Set(linked.map((article) => article.source_name).filter(Boolean));
  if (source?.name) publishers.add(source.name);
  const related = Array.isArray(event.related) ? event.related : [];
  const ingest = event.ingest_source;
  const discoveredVia =
    ingest && source && ingest.name !== source.name ? ingest.name : undefined;
  const hasOfficialEvidence =
    isOfficialTier(source?.tier) ||
    linked.some((article) => isOfficialTier(article.source_tier)) ||
    sourceLabel === 'Research paper';

  const showImage = Boolean(safeImageUrl);
  const publisherCount = Math.max(publishers.size, 1);
  const openLabel = OPEN_LABEL[sourceLabel] ?? 'Open source';

  return (
    <main className="flex-1 bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#event-body"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to event
      </a>
      <div className="intel-shell py-7 lg:py-9">
        <div className="mx-auto max-w-[1360px]">
        <nav className="mb-7" aria-label="Breadcrumb">
          <Link
            href="/"
            className="inline-flex items-center text-[13px] font-medium text-secondary transition-colors hover:text-ink"
          >
            ← All developments
          </Link>
        </nav>

        <div
          id="event-body"
          className="grid grid-cols-1 gap-12 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px] xl:gap-16"
        >
          <article className="min-w-0 space-y-10">
            <header>
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-semibold uppercase tracking-[0.14em]">
                <CategoryTag category={event.category} />
                <span className={tier.badge}>{tier.label}</span>
                {isUpdate ? (
                  <span className="rounded-[3px] border border-accent/40 px-1 py-px text-[10px] text-accent">Updated</span>
                ) : null}
              </p>
              <h1 className="font-display mt-3 text-[2.1rem] font-semibold leading-[1.08] text-ink md:text-[2.9rem]">
                {event.headline}
              </h1>
              {summary ? (
                <p className="mt-4 text-[18.5px] leading-[1.6] text-secondary">{summary}</p>
              ) : (
                <p className="mt-4 text-sm leading-relaxed text-muted">
                  No source-grounded summary was extracted. The source link remains available.
                </p>
              )}
              <div className="mt-5 flex flex-wrap items-center justify-between gap-x-6 gap-y-3 border-y border-line py-3">
                <p className="text-[13px] text-muted">
                  {source?.name ? <span className="font-medium text-ink">{source.name}</span> : null}
                  {source?.name && displayTime ? ' · ' : null}
                  {displayTime ? <time dateTime={occurred}>{displayTime}</time> : null}
                  {publisherCount > 1 ? ` · ${publisherCount} publishers` : ''}
                  {updatedAt ? (
                    <span>
                      {' · '}
                      <span className="text-accent">Updated</span>{' '}
                      <time dateTime={event.created_at}>{updatedAt}</time>
                    </span>
                  ) : null}
                </p>
                {sourceHref ? (
                  <a
                    href={sourceHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${openLabel}: ${source?.name ?? 'source'} (opens in a new tab)`}
                    className="inline-flex items-center gap-1.5 rounded-[4px] border border-accent/50 px-3 py-1.5 text-[13px] font-medium text-accent transition-colors hover:bg-accent/10"
                  >
                    {openLabel}
                    <span aria-hidden="true">↗</span>
                  </a>
                ) : null}
              </div>
              {showImage ? (
                <figure className="mt-6">
                  <EventImage
                    id={event.id}
                    size="lead"
                    category={event.category}
                    priority
                    sizes="(min-width: 1024px) 880px, 100vw"
                    className={`w-full rounded-[var(--radius-card)] border border-line ${
                      imageRole === 'hero' ? 'aspect-[16/9]' : 'aspect-[2/1]'
                    }`}
                  />
                  {source?.name ? (
                    <figcaption className="mt-2 text-[12px] text-muted">Image: {source.name}</figcaption>
                  ) : null}
                </figure>
              ) : null}
            </header>

            {keyChanges.length > 0 ? (
              <section aria-labelledby="key-changes">
                <h2 id="key-changes" className="font-display mb-3 text-[1.35rem] font-semibold text-ink">
                  What changed
                </h2>
                <ol className="space-y-3">
                  {keyChanges.map((item, idx) => (
                    <li key={idx} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3">
                      <span className="tabular pt-0.5 font-mono text-[12px] text-muted">
                        {String(idx + 1).padStart(2, '0')}
                      </span>
                      <span className="text-[16px] leading-relaxed text-secondary">{item}</span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {citations.length > 0 ? (
              <section aria-labelledby="evidence">
                <h2 id="evidence" className="font-display mb-1 text-[1.35rem] font-semibold text-ink">
                  In the source&apos;s words
                </h2>
                <p className="mb-4 text-[12.5px] text-muted">
                  Quoted verbatim from {source?.name ?? 'the source'}; each quote was checked against the article text.
                </p>
                <ul className="space-y-4">
                  {citations.map((citation, idx) => (
                    <li key={idx}>
                      <blockquote className="font-display border-l-2 border-accent/60 pl-4 text-[1.15rem] italic leading-relaxed text-secondary">
                        {citation}
                      </blockquote>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {entities.length > 0 ? (
              <section aria-labelledby="entities">
                <h2 id="entities" className="font-display mb-3 text-[1.35rem] font-semibold text-ink">
                  Who is involved
                </h2>
                <ul className="flex flex-wrap gap-2">
                  {entities.slice(0, ENTITY_PREVIEW).map((entity) => (
                    <EntityChip key={entity} name={entity} />
                  ))}
                </ul>
                {entities.length > ENTITY_PREVIEW ? (
                  <details className="mt-2">
                    <summary className="w-fit cursor-pointer text-[13px] text-muted hover:text-ink">
                      {entities.length - ENTITY_PREVIEW} more mentioned
                    </summary>
                    <ul className="mt-2 flex flex-wrap gap-2">
                      {entities.slice(ENTITY_PREVIEW).map((entity) => (
                        <EntityChip key={entity} name={entity} />
                      ))}
                    </ul>
                  </details>
                ) : null}
              </section>
            ) : null}

            {related.length > 0 ? (
              <section aria-labelledby="related">
                <h2 id="related" className="font-display mb-1 text-[1.35rem] font-semibold text-ink">
                  Related developments
                </h2>
                <ul>
                  {related.map((item) => (
                    <li key={item.id} className="group relative border-b border-line py-3.5 last:border-b-0">
                      <p className="flex flex-wrap items-center gap-x-2 text-[12px] text-muted">
                        <CategoryTag category={item.category} />
                        <span>{[item.reason, formatUtcWhen(item.event_time)].filter(Boolean).join(' · ')}</span>
                      </p>
                      <Link
                        href={`/events/${item.id}`}
                        className="card-link headline-hover font-display mt-1 block text-[1.15rem] leading-snug text-ink"
                      >
                        {item.headline}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </article>

          <aside className="min-w-0 space-y-4 lg:sticky lg:top-20 lg:self-start" aria-label="Facts and sources">
            <section className="rounded-md border border-line bg-surface p-5">
              <SideHeading>At a glance</SideHeading>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-2 text-[13px]">
                <dt className="text-muted">Occurred</dt>
                <dd className="tabular text-ink">{displayTime || '—'}</dd>
                <dt className="text-muted">First recorded</dt>
                <dd className="tabular text-ink">{firstSeen}</dd>
                <dt className="text-muted">Importance</dt>
                <dd className="text-ink">
                  <span className={tier.badge}>{tier.label}</span>
                  <span className="tabular text-muted"> · {event.importance_score ?? 0}/100</span>
                </dd>
                <dt className="text-muted">Publishers</dt>
                <dd className="tabular text-ink">{publisherCount}</dd>
                <dt className="text-muted">Reports</dt>
                <dd className="tabular text-ink">
                  {Math.max(linked.length, 1)}
                  {isUpdate ? <span className="text-muted"> · version {version}</span> : null}
                </dd>
              </dl>
              <p className="mt-3 border-t border-line pt-3 text-[12px] leading-relaxed text-muted">
                {linked.length > 1
                  ? 'Every report of this development is gathered here instead of appearing as a separate story.'
                  : 'One report so far. Later reports of the same development are added here.'}
              </p>
            </section>

            <section className="rounded-md border border-line bg-surface p-5">
              <SideHeading>Source</SideHeading>
              <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-secondary">{sourceLabel}</p>
              <p className="mt-1 text-[15px] font-medium text-ink">{source?.name ?? 'Unknown source'}</p>
              {displayTime ? <p className="mt-0.5 text-[13px] text-muted">Published {displayTime}</p> : null}
              {discoveredVia ? <p className="mt-0.5 text-[13px] text-muted">Found via {discoveredVia}</p> : null}
              {sourceHref ? (
                <a
                  href={sourceHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${openLabel}: ${source?.name ?? 'source'} (opens in a new tab)`}
                  className="mt-3 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                >
                  {openLabel}
                  <span aria-hidden="true">↗</span>
                </a>
              ) : (
                <p className="mt-3 text-sm text-muted">No source URL was recorded.</p>
              )}
              {!hasOfficialEvidence ? (
                <p className="mt-4 border-t border-line pt-3 text-[12px] leading-relaxed text-muted">
                  No official announcement was among the collected sources. That does not mean one
                  does not exist.
                </p>
              ) : null}
            </section>

            {supporting.length > 0 ? (
              <section className="rounded-md border border-line bg-surface p-5">
                <SideHeading>Supporting coverage</SideHeading>
                <ul className="space-y-3.5">
                  {supporting.map((article, idx) => {
                    const href = safeHttpUrl(article.url);
                    const label = evidenceLabel({ url: href, tier: article.source_tier });
                    const when = published(article.published_at);
                    return (
                      <li key={`${article.url}-${idx}`} className="min-w-0">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                          {label}
                          {when ? <span className="font-normal normal-case tracking-normal"> · {when}</span> : null}
                        </p>
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`${label}: ${article.source_name}, ${article.title} (opens in a new tab)`}
                            className="mt-0.5 block text-sm text-accent hover:underline"
                          >
                            {article.source_name}
                            <span aria-hidden="true"> ↗</span>
                          </a>
                        ) : (
                          <span className="mt-0.5 block text-sm text-secondary">{article.source_name}</span>
                        )}
                        <p className="line-clamp-2 text-[12px] leading-snug text-muted">{article.title}</p>
                      </li>
                    );
                  })}
                </ul>
              </section>
            ) : null}

            {versions.length > 0 ? (
              <section className="rounded-md border border-line bg-surface p-5">
                <SideHeading>Update history</SideHeading>
                <p className="mb-3 text-[12px] leading-relaxed text-muted">
                  The source page changed materially after it was first recorded. This page shows the latest version.
                </p>
                <ol className="space-y-2.5">
                  <li>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-secondary">
                      Version {version} · current · {updatedAt}
                    </p>
                  </li>
                  {versions.map((item) => (
                    <li key={item.id}>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                        Version {item.version} · {formatUtcMeta(item.recorded_at)}
                      </p>
                      <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-secondary">{item.headline}</p>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}
          </aside>
        </div>
        </div>
      </div>
    </main>
  );
}

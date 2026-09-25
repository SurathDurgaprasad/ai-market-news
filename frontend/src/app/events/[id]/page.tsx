import React, { cache } from 'react';
import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound, redirect, unstable_rethrow } from 'next/navigation';
import { API_V1 } from '@/lib/api';
import { formatCitation } from '@/lib/citations';
import { detailImageClass, importanceMeta, type ImageRole } from '@/lib/importance';
import { displaySource, evidenceLabel, isOfficialTier, type SourceRef } from '@/lib/sources';
import { factualSummary, formatUtcMeta, formatUtcWhen, hasClockTime, formatUtcDay } from '@/lib/time';
import { safeHttpUrl } from '@/lib/urls';

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
  return { title: loaded.kind === 'missing' ? 'Event not found' : 'Event unavailable' };
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
          <h1 className="mb-3 text-2xl font-semibold text-ink">Event temporarily unavailable</h1>
          <p className="mb-8 text-muted">The intelligence API could not be reached. Try again shortly.</p>
          <Link href="/" className="text-accent hover:underline">
            ← Back to overview
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

  return (
    <main className="flex-1 bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#event-body"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to event
      </a>
      <div className="intel-shell py-6 lg:py-8">
        <nav className="mb-6" aria-label="Breadcrumb">
          <Link
            href="/"
            className="inline-flex items-center text-[13px] font-medium text-secondary transition-colors hover:text-ink"
          >
            ← Overview
          </Link>
        </nav>

        <header className="mb-8 max-w-4xl">
          <p className="text-[11px] font-semibold uppercase tracking-[0.16em]">
            <span className={tier.badge}>{tier.label}</span>
            {event.category ? <span className="text-muted"> · {event.category}</span> : null}
          </p>
          <h1 className="mt-3 text-[1.75rem] font-semibold leading-[1.2] tracking-[-0.015em] text-ink md:text-[2.25rem] xl:text-[2.5rem]">
            {event.headline}
          </h1>
          <p className="mt-4 text-[13px] text-muted">
            {source?.name ? <span className="font-medium text-secondary">{source.name}</span> : null}
            {source?.name && displayTime ? ' · ' : null}
            {displayTime ? <time dateTime={occurred}>{displayTime}</time> : null}
            {updatedAt ? (
              <span>
                {' · '}
                <span className="text-accent">Updated</span>{' '}
                <time dateTime={event.created_at}>{updatedAt}</time>
              </span>
            ) : null}
          </p>
        </header>

        {safeImageUrl ? (
          <div
            className={`relative mb-8 w-full max-w-4xl overflow-hidden rounded-md border border-line bg-elevated ${detailImageClass(imageRole)}`}
          >
            <img
              src={safeImageUrl}
              alt=""
              decoding="async"
              referrerPolicy="no-referrer"
              className="absolute inset-0 h-full w-full object-cover object-center"
            />
          </div>
        ) : null}

        <div
          id="event-body"
          className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.9fr)] lg:gap-14"
        >
          <div className="min-w-0 space-y-10">
            <section aria-labelledby="what-happened">
              <h2 id="what-happened" className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                What happened
              </h2>
              {summary ? (
                <p className="max-w-[64ch] text-[17px] leading-[1.7] text-secondary">{summary}</p>
              ) : (
                <p className="max-w-[64ch] text-sm leading-relaxed text-muted">
                  No source-grounded summary was extracted. The source link remains available.
                </p>
              )}
            </section>

            {keyChanges.length > 0 ? (
              <section aria-labelledby="key-changes">
                <h2 id="key-changes" className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  Key changes
                </h2>
                <ol className="max-w-[64ch] space-y-3">
                  {keyChanges.map((item, idx) => (
                    <li key={idx} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-3">
                      <span className="pt-0.5 font-mono text-[11px] tracking-wider text-muted">
                        {String(idx + 1).padStart(2, '0')}
                      </span>
                      <span className="text-[15px] leading-relaxed text-secondary">{item}</span>
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {entities.length > 0 ? (
              <section aria-labelledby="entities">
                <h2 id="entities" className="mb-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  Named in the source
                </h2>
                <ul className="flex max-w-[64ch] flex-wrap gap-2">
                  {entities.slice(0, ENTITY_PREVIEW).map((entity) => (
                    <EntityChip key={entity} name={entity} />
                  ))}
                </ul>
                {entities.length > ENTITY_PREVIEW ? (
                  <details className="mt-2 max-w-[64ch]">
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
                <h2 id="related" className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  Related developments
                </h2>
                <ul>
                  {related.map((item) => (
                    <li key={item.id} className="border-b border-line py-3 last:border-b-0">
                      <p className="text-[12px] text-muted">
                        {[item.reason, item.category, formatUtcWhen(item.event_time)].filter(Boolean).join(' · ')}
                      </p>
                      <Link href={`/events/${item.id}`} className="mt-0.5 block text-[15px] leading-snug text-ink hover:text-accent">
                        {item.headline}
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>

          <aside className="min-w-0 space-y-5 lg:sticky lg:top-6 lg:self-start" aria-label="Evidence">
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
                  aria-label={`${OPEN_LABEL[sourceLabel] ?? 'Open source'}: ${source?.name ?? 'source'} (opens in a new tab)`}
                  className="mt-3 inline-flex w-fit items-center gap-1.5 text-sm font-medium text-accent hover:underline"
                >
                  {OPEN_LABEL[sourceLabel] ?? 'Open source'}
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

            <section className="rounded-md border border-line bg-surface p-5">
              <SideHeading>Canonical event</SideHeading>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-[13px]">
                <dt className="text-muted">Articles</dt>
                <dd className="text-secondary">{Math.max(linked.length, 1)}</dd>
                <dt className="text-muted">Publishers</dt>
                <dd className="text-secondary">{Math.max(publishers.size, 1)}</dd>
                <dt className="text-muted">First recorded</dt>
                <dd className="text-secondary">{firstSeen}</dd>
                {isUpdate ? (
                  <>
                    <dt className="text-muted">Version</dt>
                    <dd className="text-secondary">{version} · source page updated</dd>
                  </>
                ) : null}
              </dl>
              <p className="mt-3 text-[12px] leading-relaxed text-muted">
                {linked.length > 1
                  ? 'Reports of the same development are merged into this one event and kept below as evidence.'
                  : 'One article reports this development so far. Later reports of it are merged here.'}
              </p>
            </section>

            {versions.length > 0 ? (
              <section className="rounded-md border border-line bg-surface p-5">
                <SideHeading>Update history</SideHeading>
                <p className="mb-3 text-[12px] leading-relaxed text-muted">
                  The source page changed materially after it was first recorded. This card shows the latest version.
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

            {citations.length > 0 ? (
              <section className="rounded-md border border-line bg-surface p-5">
                <SideHeading>Quoted from the source</SideHeading>
                <ul className="space-y-3">
                  {citations.map((citation, idx) => (
                    <li
                      key={idx}
                      className="border-l-2 border-success/40 pl-3 text-[14px] leading-relaxed text-secondary"
                    >
                      {citation}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

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
          </aside>
        </div>
      </div>
    </main>
  );
}

import React from 'react';
import Link from 'next/link';
import { API_V1 } from '@/lib/api';
import { formatCitation } from '@/lib/citations';
import { detailImageClass, importanceMeta, type ImageRole } from '@/lib/importance';
import { evidenceLabel } from '@/lib/sources';
import { factualSummary, formatUtcMeta } from '@/lib/time';
import { safeHttpUrl } from '@/lib/urls';

async function getEvent(id: string) {
  try {
    const res = await fetch(`${API_V1}/events/${id}`, {
      cache: 'no-store',
    });
    if (!res.ok) {
      if (res.status === 404) return null;
      throw new Error(`API returned ${res.status}`);
    }
    return await res.json();
  } catch (error) {
    console.error('Failed to fetch event detail:', error);
    return null;
  }
}

function changePoints(value?: string | null): string[] {
  if (!value) return [];
  return value
    .split('\n')
    .map((line) => line.replace(/^\s*[-•]\s*/, '').trim())
    .filter(Boolean);
}

function padIndex(index: number): string {
  return String(index + 1).padStart(2, '0');
}

function asImageRole(value: unknown): ImageRole | undefined {
  if (value === 'hero' || value === 'source' || value === 'none') return value;
  return undefined;
}

export default async function EventDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const event = await getEvent(id);

  if (!event) {
    return (
      <main className="min-h-screen bg-canvas p-16 text-ink selection:bg-accent/30">
        <div className="intel-shell text-center">
          <h1 className="mb-4 text-3xl font-semibold text-danger">Event not found</h1>
          <p className="mb-8 text-muted">
            The event does not exist or the backend is unreachable.
          </p>
          <Link href="/" className="text-accent hover:underline">
            ← Back to Intelligence
          </Link>
        </div>
      </main>
    );
  }

  const officialHref =
    safeHttpUrl(event.article_url) ||
    safeHttpUrl(event.official_source?.url) ||
    safeHttpUrl(event.primary_source?.url);
  const tier = importanceMeta(event.importance_score ?? 0);
  const displayTime = formatUtcMeta(event.event_time ?? event.created_at);
  const summary = factualSummary(event.short_summary);
  const imageRole = asImageRole(event.image_role);
  const safeImageUrl =
    imageRole === 'none' ? undefined : safeHttpUrl(event.image_url, { keepQuery: true });
  const citations = Array.isArray(event.citations)
    ? event.citations.map((item: string) => formatCitation(item)).filter(Boolean)
    : [];
  const keyChanges = changePoints(event.what_changed);
  const entities: string[] = Array.isArray(event.entities)
    ? event.entities.map((item: string) => item.trim()).filter(Boolean)
    : [];
  const supporting = Array.isArray(event.linked_articles)
    ? event.linked_articles.filter((article: { link_type?: string }) => article.link_type !== 'primary')
    : [];
  const sourceName =
    event.official_source?.name || event.primary_source?.name || 'Unknown source';
  const primaryLabel = evidenceLabel({
    url: officialHref,
    tier: event.official_source?.tier || event.primary_source?.tier,
    official: Boolean(event.official_source) || event.primary_source?.tier === 'primary',
  });

  return (
    <main className="min-h-screen bg-canvas text-ink selection:bg-accent/30">
      <a
        href="#event-body"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-canvas"
      >
        Skip to event
      </a>
      <div className="intel-shell py-8 lg:py-10">
        <nav className="mb-6">
          <Link
            href="/"
            className="inline-flex items-center text-sm font-medium text-secondary transition-colors hover:text-ink"
          >
            ← Back to Intelligence
          </Link>
        </nav>

        {safeImageUrl ? (
          <div
            className={`relative mb-8 w-full overflow-hidden rounded-lg border border-line ${detailImageClass(imageRole)}`}
          >
            <img
              src={safeImageUrl}
              alt=""
              role="presentation"
              className="absolute inset-0 h-full w-full object-cover object-center"
            />
          </div>
        ) : null}

        <header className="mb-10 max-w-4xl">
          <p className={`text-[12px] font-semibold uppercase tracking-[0.16em] ${tier.badge}`}>
            {tier.label}
          </p>
          <p className="mt-4 text-[15px] font-medium text-ink">{sourceName}</p>
          {displayTime ? (
            <time
              className="mt-1 block text-[13px] text-muted"
              dateTime={event.event_time ?? event.created_at}
            >
              {displayTime}
            </time>
          ) : null}
          <h1 className="mt-5 text-[2rem] font-semibold leading-[1.18] tracking-[-0.02em] text-ink md:text-[2.75rem] xl:text-[3.1rem]">
            {event.headline}
          </h1>
        </header>

        <div
          id="event-body"
          className="grid grid-cols-1 items-stretch gap-10 lg:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.85fr)] lg:gap-14"
        >
          <div className="space-y-12">
            <section>
              <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                What happened
              </h2>
              {summary ? (
                <p className="max-w-[58ch] text-[17px] leading-[1.72] text-secondary md:text-[18px]">
                  {summary}
                </p>
              ) : (
                <div className="max-w-[58ch] rounded-lg border border-warning/40 bg-warning/10 px-5 py-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-warning">
                    Incomplete extraction
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-muted">
                    No source-grounded summary is available yet. The primary source remains available.
                  </p>
                </div>
              )}
            </section>

            <section>
              <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                Key changes
              </h2>
              {keyChanges.length > 0 ? (
                <ol className="max-w-[58ch] space-y-4">
                  {keyChanges.map((item: string, idx: number) => (
                    <li key={idx} className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-3">
                      <span className="pt-0.5 font-mono text-[11px] tracking-wider text-muted">
                        {padIndex(idx)}
                      </span>
                      <span className="text-[15px] leading-relaxed text-secondary">{item}</span>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-sm text-muted">No structured change list was extracted from the source.</p>
              )}
            </section>

            <section>
              <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                Entities
              </h2>
              {entities.length > 0 ? (
                <p className="max-w-[58ch] text-[14px] leading-relaxed text-secondary">
                  {entities.join(' · ')}
                </p>
              ) : (
                <p className="text-sm text-muted">None extracted.</p>
              )}
            </section>
          </div>

          <aside className="lg:sticky lg:top-8 lg:self-stretch">
            <section className="flex h-full min-h-[28rem] flex-col rounded-lg border border-line bg-elevated p-6 lg:p-7">
              <h2 className="mb-6 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                Evidence
              </h2>
              <div className="flex flex-1 flex-col gap-7">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                    Primary source
                  </p>
                  <p className="mt-2 text-[15px] font-medium text-ink">{sourceName}</p>
                  {displayTime ? (
                    <p className="mt-1 text-[13px] text-muted">{displayTime}</p>
                  ) : null}
                </div>

                {officialHref ? (
                  <a
                    href={officialHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${primaryLabel}: ${sourceName}`}
                    className="inline-flex w-fit items-center gap-2 text-sm font-medium text-accent transition-colors hover:text-accent"
                  >
                    {primaryLabel}
                    <span aria-hidden="true">↗</span>
                  </a>
                ) : (
                  <p className="text-sm text-muted">No source URL.</p>
                )}

                {citations.length > 0 ? (
                  <div className="border-t border-line pt-6">
                    <p className="mb-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-success">
                      Verified quotes
                    </p>
                    <ul className="space-y-4">
                      {citations.map((citation: string, idx: number) => (
                        <li
                          key={idx}
                          className="border-l-2 border-success/40 pl-3.5 text-[14px] leading-relaxed text-secondary"
                        >
                          {citation}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <div className="border-t border-line pt-6">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                      Source available
                    </p>
                    <p className="mt-2 text-sm leading-relaxed text-muted">
                      Evidence verification unavailable.
                    </p>
                  </div>
                )}
              </div>
            </section>

            {supporting.length > 0 ? (
              <section className="mt-5 rounded-lg border border-line bg-elevated p-6">
                <h2 className="mb-4 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                  Supporting sources
                </h2>
                <ul className="space-y-3">
                  {supporting.map(
                    (
                      article: {
                        title: string;
                        url: string;
                        source_name: string;
                        source_tier?: string;
                        link_type: string;
                      },
                      idx: number,
                    ) => {
                      const href = safeHttpUrl(article.url);
                      const label = evidenceLabel({
                        url: href,
                        tier: article.source_tier,
                      });
                      return (
                        <li key={idx} className="flex flex-col gap-0.5">
                          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink0">
                            {label}
                          </span>
                          {href ? (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-label={`${label}: ${article.source_name}`}
                              className="text-sm text-accent hover:text-accent"
                            >
                              {article.source_name}
                            </a>
                          ) : (
                            <span className="text-sm text-muted">{article.source_name}</span>
                          )}
                          <span className="line-clamp-1 text-[12px] text-ink0">{article.title}</span>
                        </li>
                      );
                    },
                  )}
                </ul>
              </section>
            ) : null}
          </aside>
        </div>
      </div>
    </main>
  );
}

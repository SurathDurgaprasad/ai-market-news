import React from 'react';
import type { Metadata } from 'next';
import { unstable_rethrow } from 'next/navigation';
import { API_V1 } from '@/lib/api';
import { formatUtcMeta } from '@/lib/time';
import { readableIngest } from '@/lib/sources';

interface AdminSource {
  id: string;
  name: string;
  url: string;
  tier: string;
  health_status: string;
  last_fetch_at: string | null;
  last_error_info: string | null;
  last_ingest_summary: string | null;
  consecutive_failures: number;
  polling_tier: string | null;
  enabled: boolean;
}

export const metadata: Metadata = { title: 'Sources' };

async function getSources(): Promise<AdminSource[] | null> {
  try {
    const res = await fetch(`${API_V1}/sources/?limit=1000`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`API returned status ${res.status}`);
    return await res.json();
  } catch (error) {
    unstable_rethrow(error);
    console.error('Failed to fetch sources', error);
    return null;
  }
}

function healthClass(source: AdminSource): string {
  if (!source.enabled) return 'text-muted';
  if (source.health_status === 'healthy') return 'text-success';
  if (source.health_status === 'failing') return 'text-danger';
  return 'text-warning';
}

function HealthPill({ source }: { source: AdminSource }) {
  const label = source.enabled ? source.health_status : 'disabled';
  return (
    <span className={`inline-flex items-center gap-1.5 text-[12.5px] font-medium ${healthClass(source)}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {label}
    </span>
  );
}

// Error strings from the fetcher can carry a long help URL; the first line is the reason.
function firstLine(value: string | null): string {
  return (value ?? '').split('\n')[0].trim();
}

export default async function AdminSourcesPage() {
  const sources = await getSources();
  const rows = (sources ?? []).slice().sort((a, b) => {
    // Actionable first: failing, then degraded, healthy, and disabled last.
    const rank = (s: AdminSource) =>
      !s.enabled ? 3 : s.health_status === 'failing' ? 0 : s.health_status === 'healthy' ? 2 : 1;
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
  const th = 'px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.14em] text-muted';
  const td = 'px-4 py-3 align-top text-[13px]';

  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="intel-shell py-6 lg:py-8">
        <header className="mb-6 border-b border-line pb-5">
          <h1 className="text-[1.6rem] font-semibold tracking-tight">Sources</h1>
          <p className="mt-1 text-[13px] text-muted">
            Ingestion health for the registry. Add or disable a source with manage_sources.py; the scheduler
            picks it up on the next tick. Times in UTC.
          </p>
          {sources ? (
            <dl className="mt-4 flex flex-wrap gap-2">
              {(
                [
                  ['Healthy', rows.filter((r) => r.enabled && r.health_status === 'healthy').length, 'text-success'],
                  ['Degraded', rows.filter((r) => r.enabled && r.health_status !== 'healthy' && r.health_status !== 'failing').length, 'text-warning'],
                  ['Failing', rows.filter((r) => r.enabled && r.health_status === 'failing').length, 'text-danger'],
                  ['Disabled', rows.filter((r) => !r.enabled).length, 'text-muted'],
                ] as const
              ).map(([label, count, tone]) => (
                <div key={label} className="rounded-[var(--radius-card)] border border-line bg-surface px-3.5 py-2">
                  <dt className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-muted">{label}</dt>
                  <dd className={`tabular text-[18px] font-semibold ${count > 0 ? tone : 'text-muted'}`}>{count}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </header>

        {sources === null ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-6 text-center text-danger" role="alert">
            <p className="font-semibold">Intelligence API unavailable</p>
          </div>
        ) : (
          <>
          <ul className="divide-y divide-line rounded-md border border-line bg-surface md:hidden" aria-label="Source ingestion health">
            {rows.length === 0 ? (
              <li className="px-4 py-8 text-center text-sm text-muted">No sources are registered.</li>
            ) : (
              rows.map((source) => (
                <li key={source.id} className="px-4 py-3 text-[13px]">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="min-w-0 truncate font-medium text-ink">{source.name}</p>
                    <span className="shrink-0"><HealthPill source={source} /></span>
                  </div>
                  <p className="mt-0.5 text-[12px] text-muted">
                    {source.tier} · {source.last_fetch_at ? `last fetch ${formatUtcMeta(source.last_fetch_at)}` : 'never fetched'}
                    {source.consecutive_failures > 0 ? ` · ${source.consecutive_failures} consecutive failures` : ''}
                  </p>
                  {source.last_error_info ? (
                    <p className="mt-1 text-[12px] text-warning">{firstLine(source.last_error_info)}</p>
                  ) : source.last_ingest_summary ? (
                    <p className="mt-1 text-[12px] text-muted">{readableIngest(source.last_ingest_summary)}</p>
                  ) : null}
                </li>
              ))
            )}
          </ul>
          <div className="hidden overflow-x-auto rounded-md border border-line bg-surface md:block">
            <table className="min-w-full divide-y divide-line">
              <caption className="sr-only">Source ingestion health</caption>
              <thead className="bg-elevated">
                <tr>
                  <th scope="col" className={th}>Source</th>
                  <th scope="col" className={th}>Tier</th>
                  <th scope="col" className={th}>Health</th>
                  <th scope="col" className={th}>Last successful fetch</th>
                  <th scope="col" className={th}>Last result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm text-muted">
                      No sources are registered.
                    </td>
                  </tr>
                ) : (
                  rows.map((source) => (
                    <tr key={source.id}>
                      <td className={`${td} font-medium text-ink`}>
                        {source.name}
                        <p className="mt-0.5 max-w-[28ch] truncate text-[12px] font-normal text-muted">{source.url}</p>
                      </td>
                      <td className={`${td} text-secondary`}>{source.tier}</td>
                      <td className={`${td} whitespace-nowrap`}>
                        <HealthPill source={source} />
                        {source.consecutive_failures > 0 ? (
                          <p className="text-[12px] text-muted">{source.consecutive_failures} consecutive failures</p>
                        ) : null}
                      </td>
                      <td className={`${td} whitespace-nowrap text-secondary`}>
                        {source.last_fetch_at ? formatUtcMeta(source.last_fetch_at) : 'Never'}
                      </td>
                      <td className={`${td} max-w-[42ch] text-muted`}>
                        {source.last_error_info ? (
                          <span className="text-warning">{firstLine(source.last_error_info)}</span>
                        ) : (
                          readableIngest(source.last_ingest_summary)
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </main>
  );
}

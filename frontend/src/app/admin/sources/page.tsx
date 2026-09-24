import React from 'react';
import { unstable_rethrow } from 'next/navigation';
import { API_V1 } from '@/lib/api';
import { formatUtcMeta } from '@/lib/time';

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

// Error strings from the fetcher can carry a long help URL; the first line is the reason.
function firstLine(value: string | null): string {
  return (value ?? '').split('\n')[0].trim();
}

export default async function AdminSourcesPage() {
  const sources = await getSources();
  const rows = (sources ?? []).slice().sort((a, b) => {
    const rank = (s: AdminSource) => (s.health_status === 'failing' ? 0 : s.health_status === 'healthy' ? 2 : 1);
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
        </header>

        {sources === null ? (
          <div className="rounded-md border border-danger/40 bg-danger/10 p-6 text-center text-danger" role="alert">
            <p className="font-semibold">Intelligence API unavailable</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-md border border-line bg-surface">
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
                        <span className={healthClass(source)}>
                          {source.enabled ? source.health_status : 'disabled'}
                        </span>
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
                          source.last_ingest_summary ?? '—'
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}

import React from 'react';
import { API_V1 } from '@/lib/api';

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

async function getSources(): Promise<AdminSource[]> {
  try {
    const res = await fetch(`${API_V1}/sources/?limit=1000`, {
      next: { revalidate: 30 }
    });
    if (!res.ok) throw new Error('API failed');
    return await res.json();
  } catch (error) {
    console.error('Failed to fetch sources', error);
    return [];
  }
}

export default async function AdminSourcesPage() {
  const sources = await getSources();

  return (
    <main className="min-h-screen bg-canvas text-ink">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        <header className="mb-8 border-b border-line pb-6">
          <h1 className="text-3xl font-semibold">Sources</h1>
          <p className="mt-2 text-muted">
            Ingestion health for the registry. Add or disable a source with manage_sources.py; the scheduler picks it up on the next tick.
          </p>
        </header>

        <div className="overflow-hidden rounded-lg border border-line bg-surface">
          <table className="min-w-full divide-y divide-line">
            <thead className="bg-elevated">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">Source Name</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">Tier</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">Health</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-muted">Last Fetch</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-sm text-muted">
                    No sources found or backend unreachable.
                  </td>
                </tr>
              ) : (
                sources.map((source: AdminSource) => (
                  <tr key={source.id}>
                    <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-ink">{source.name}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-secondary">{source.tier}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <span className={source.health_status === 'healthy' ? 'text-success' : source.health_status === 'failing' ? 'text-danger' : 'text-warning'}>
                        {source.enabled ? source.health_status : 'disabled'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-secondary">
                      {source.last_fetch_at ? new Date(source.last_fetch_at).toLocaleString() : 'Never'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

      </div>
    </main>
  );
}

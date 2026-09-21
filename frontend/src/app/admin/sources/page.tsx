import React from 'react';
import Link from 'next/link';
import { API_V1 } from '@/lib/api';

async function getSources() {
  try {
    const res = await fetch(`${API_V1}/sources/`, {
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
    <main className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
        
        <header className="mb-8 flex items-center justify-between border-b border-white/10 pb-6">
          <div>
            <h1 className="text-3xl font-bold">Admin: Source Management</h1>
            <p className="mt-2 text-gray-400">Manage ingestion sources, health status, and tiers.</p>
          </div>
          <button className="rounded-md bg-blue-600 px-4 py-2 font-semibold text-white hover:bg-blue-500">
            + Add Source
          </button>
        </header>

        <div className="overflow-hidden rounded-lg border border-white/10 bg-white/5">
          <table className="min-w-full divide-y divide-white/10">
            <thead className="bg-white/5">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">Source Name</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">Tier</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">Health</th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-400">Last Fetch</th>
                <th scope="col" className="relative px-6 py-3"><span className="sr-only">Edit</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10 bg-transparent">
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-sm text-gray-500">
                    No sources found or backend unreachable.
                  </td>
                </tr>
              ) : (
                sources.map((source: any) => (
                  <tr key={source.id} className="hover:bg-white/5 transition-colors">
                    <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-white">{source.name}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-300">{source.tier}</td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm">
                      <span className={`inline-flex rounded-full px-2 text-xs font-semibold leading-5 ${source.health_status === 'healthy' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                        {source.health_status}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-300">
                      {source.last_fetch_at ? new Date(source.last_fetch_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="whitespace-nowrap px-6 py-4 text-right text-sm font-medium">
                      <a href="#" className="text-blue-400 hover:text-blue-300">Edit</a>
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

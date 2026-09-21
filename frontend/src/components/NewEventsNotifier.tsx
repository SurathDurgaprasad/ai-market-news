'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { API_V1 } from '@/lib/api';

export const NewEventsNotifier: React.FC<{ latestEventTimestamp: string }> = ({
  latestEventTimestamp,
}) => {
  const [newCount, setNewCount] = useState(0);
  const router = useRouter();

  useEffect(() => {
    if (!latestEventTimestamp) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(
          `${API_V1}/events/new_count?since=${encodeURIComponent(latestEventTimestamp)}`,
          { cache: 'no-store' },
        );
        if (res.ok) {
          const data = await res.json();
          setNewCount(data.new_events_count || 0);
        }
      } catch (e) {
        console.error('Failed to check for new events', e);
      }
    }, 20000);

    return () => clearInterval(interval);
  }, [latestEventTimestamp]);

  if (newCount === 0) return null;

  return (
    <button
      type="button"
      onClick={() => {
        setNewCount(0);
        router.refresh();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }}
      className="ml-auto inline-flex flex-col items-start rounded-md border border-sky-400/35 bg-sky-500/10 px-3.5 py-2 text-left transition-colors hover:border-sky-300/50 hover:bg-sky-500/15 sm:ml-0"
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-sky-300">
        {newCount} new development{newCount > 1 ? 's' : ''}
      </span>
      <span className="mt-0.5 text-[11px] text-sky-200/70">Refresh feed</span>
    </button>
  );
};

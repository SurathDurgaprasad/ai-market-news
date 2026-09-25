'use client';

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { API_V1 } from '@/lib/api';

const POLL_MS = 30_000;

export const NewEventsNotifier: React.FC<{ latestEventTimestamp: string }> = ({
  latestEventTimestamp,
}) => {
  const [newCount, setNewCount] = useState(0);
  const router = useRouter();

  useEffect(() => {
    if (!latestEventTimestamp) return;
    let cancelled = false;

    const check = async () => {
      // A background tab does not need fresh counts; it checks again on return.
      if (document.visibilityState !== 'visible') return;
      try {
        const res = await fetch(
          `${API_V1}/events/new_count?since=${encodeURIComponent(latestEventTimestamp)}&scope=week`,
          { cache: 'no-store' },
        );
        if (res.ok && !cancelled) {
          const data = await res.json();
          setNewCount(Number(data.new_events_count) || 0);
        }
      } catch {
        // The next poll retries; a transient network error is not shown to readers.
      }
    };

    const interval = setInterval(check, POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void check();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [latestEventTimestamp]);

  return (
    <div aria-live="polite">
      {newCount > 0 ? (
        <button
          type="button"
          onClick={() => {
            setNewCount(0);
            router.refresh();
            const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            window.scrollTo({ top: 0, behavior: still ? 'auto' : 'smooth' });
          }}
          className="inline-flex flex-col items-start rounded-md border border-accent/40 bg-accent/10 px-3 py-1.5 text-left transition-colors hover:border-accent hover:bg-accent/15"
        >
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-accent">
            {newCount} new development{newCount > 1 ? 's' : ''}
          </span>
          <span className="mt-0.5 text-[11px] text-secondary">Refresh</span>
        </button>
      ) : null}
    </div>
  );
};

'use client';

import { useEffect } from 'react';
import Link from 'next/link';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Unhandled error while rendering this view:', error);
  }, [error]);

  return (
    <main className="flex flex-1 items-center justify-center bg-canvas px-4 py-16 text-ink">
      <div className="max-w-md rounded-md border border-line bg-surface p-8 text-center" role="alert">
        <h1 className="mb-2 text-xl font-semibold text-ink">This view could not be loaded</h1>
        <p className="mb-6 text-sm text-muted">
          The intelligence API may be restarting. Your data is unaffected.
        </p>
        <div className="flex items-center justify-center gap-5">
          <button
            type="button"
            onClick={() => reset()}
            className="rounded-md border border-line bg-elevated px-4 py-2 text-sm font-medium text-ink transition-colors hover:border-accent"
          >
            Try again
          </button>
          <Link href="/" className="text-sm text-accent hover:underline">
            Back to overview
          </Link>
        </div>
      </div>
    </main>
  );
}

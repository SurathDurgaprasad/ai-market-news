'use client';

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Next.js Global Error Caught:', error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas text-ink">
      <div className="rounded-lg border border-danger/40 bg-danger/10 p-8 text-center">
        <h2 className="mb-4 text-2xl font-bold text-danger">Something went wrong!</h2>
        <p className="mb-6 text-secondary">
          The intelligence platform encountered an error loading this view.
        </p>
        <button
          onClick={() => reset()}
          className="rounded-md bg-danger-fill px-6 py-2 font-medium text-ink transition-colors hover:bg-danger-fill/80"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

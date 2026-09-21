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
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#0a0a0a] text-white">
      <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-8 text-center">
        <h2 className="mb-4 text-2xl font-bold text-red-400">Something went wrong!</h2>
        <p className="mb-6 text-gray-300">
          The intelligence platform encountered an error loading this view.
        </p>
        <button
          onClick={() => reset()}
          className="rounded-md bg-red-600 px-6 py-2 font-medium text-white transition-colors hover:bg-red-500"
        >
          Try again
        </button>
      </div>
    </div>
  );
}

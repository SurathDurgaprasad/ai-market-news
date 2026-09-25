'use client';

import { useState, type CSSProperties } from 'react';
import { API_V1 } from '@/lib/api';
import { categoryColor } from '@/lib/categories';

/** The API's resized copy of an event image; the publisher original is never loaded. */
export function eventImageUrl(id: string, width: 192 | 640 | 1200): string {
  return `${API_V1}/events/${encodeURIComponent(id)}/image?w=${width}`;
}

// Default source per slot; cards and the lead also offer both larger widths via srcSet.
const DEFAULT_WIDTH: Record<'thumb' | 'card' | 'lead', 192 | 640 | 1200> = { thumb: 192, card: 640, lead: 1200 };

/**
 * A fixed-ratio frame with the event's image. While loading, or if the image
 * fails, the frame shows a quiet tint of the category colour instead of a
 * broken image, so rows keep their rhythm.
 */
export function EventImage({
  id,
  size,
  category,
  className = '',
  sizes,
  priority = false,
}: {
  id: string;
  size: 'thumb' | 'card' | 'lead';
  category?: string | null;
  className?: string;
  sizes?: string;
  priority?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const src = DEFAULT_WIDTH[size];
  const style = { '--plate': categoryColor(category) } as CSSProperties;
  const srcSet = size === 'thumb' ? undefined : `${eventImageUrl(id, 640)} 640w, ${eventImageUrl(id, 1200)} 1200w`;
  return (
    <div className={`image-frame ${className}`} style={style}>
      {failed ? null : (
        // eslint-disable-next-line @next/next/no-img-element -- already resized and cached by the API
        <img
          src={eventImageUrl(id, src)}
          srcSet={srcSet}
          sizes={srcSet ? sizes : undefined}
          alt=""
          loading={priority ? 'eager' : 'lazy'}
          fetchPriority={priority ? 'high' : undefined}
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}

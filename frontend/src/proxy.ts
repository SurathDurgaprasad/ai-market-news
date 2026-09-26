import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { API_V1 } from '@/lib/api';
import { isKnownPlayer } from '@/lib/players';

/**
 * Event pages stream behind loading.tsx, and a streamed response is already
 * 200 when the page finds a missing event. The status has to be decided
 * before streaming, so the existence check runs here:
 *
 * - missing event   -> rewrite to an unmatched path: a real 404 with the
 *                      app's not-found page
 * - merged duplicate -> 308 to the canonical event
 * - API unreachable -> pass through; the page shows its unavailable state
 *
 * Player pages stream the same way; an unknown slug is a 404 without any
 * API call, because the set of players is fixed.
 */
const RESOLVE_TIMEOUT_MS = 2000;
const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;
const MISSING = '/_missing/event';

export async function proxy(request: NextRequest) {
  const [, section = '', id = ''] = request.nextUrl.pathname.split('/');
  if (section === 'players') {
    return isKnownPlayer(id) ? NextResponse.next() : NextResponse.rewrite(new URL(MISSING, request.url));
  }
  if (!UUID.test(id)) {
    return NextResponse.rewrite(new URL(MISSING, request.url));
  }

  let res: Response;
  try {
    res = await fetch(`${API_V1}/events/${encodeURIComponent(id)}/resolve`, {
      cache: 'no-store',
      signal: AbortSignal.timeout(RESOLVE_TIMEOUT_MS),
    });
  } catch {
    return NextResponse.next();
  }

  if (res.status === 404) {
    return NextResponse.rewrite(new URL(MISSING, request.url));
  }
  if (!res.ok) {
    return NextResponse.next();
  }
  try {
    const body: { canonical_id?: string } = await res.json();
    if (body.canonical_id && body.canonical_id !== id && UUID.test(body.canonical_id)) {
      return NextResponse.redirect(new URL(`/events/${body.canonical_id}`, request.url), 308);
    }
  } catch {
    // An unreadable body is not a reason to block the page.
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    {
      source: '/events/:id',
      // Prefetches of the many event links in view would each cost an API
      // round trip; the navigation itself still gets the 404/308 decision.
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
    { source: '/players/:slug' },
  ],
};

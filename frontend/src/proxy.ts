import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { API_V1 } from '@/lib/api';

/**
 * Event pages stream behind loading.tsx, and a streamed response is already
 * 200 when the page finds a missing event. The status has to be decided
 * before streaming, so the existence check runs here:
 *
 * - missing event   -> rewrite to an unmatched path: a real 404 with the
 *                      app's not-found page
 * - merged duplicate -> 308 to the canonical event
 * - API unreachable -> pass through; the page shows its unavailable state
 */
const RESOLVE_TIMEOUT_MS = 2000;
const UUID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;
const MISSING = '/_missing/event';

export async function proxy(request: NextRequest) {
  const id = request.nextUrl.pathname.split('/')[2] ?? '';
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
  matcher: '/events/:id',
};

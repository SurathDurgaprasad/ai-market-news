import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { NextRequest } from 'next/server';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  notFound: () => {
    throw new Error('NEXT_NOT_FOUND');
  },
  redirect: (url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  },
  unstable_rethrow: () => undefined,
}));

import { EventCard, type EventCardData } from '@/components/EventCard';
import { MarketOverview, type MarketOverviewData } from '@/components/MarketOverview';
import { evidenceLabel } from '@/lib/sources';
import { formatUtcCardTime, hasClockTime } from '@/lib/time';
import { proxy } from '@/proxy';
import Home from '@/app/(home)/page';
import PlayerPage from '@/app/players/[slug]/page';

const html = (node: ReactElement) => renderToStaticMarkup(node);

const EVENT: EventCardData = {
  id: '656a075f-8550-45ef-98d0-6243e9a83bd0',
  headline: "US Criticizes Australia's Proposed Algorithm Opt-Out Laws",
  short_summary: 'The US criticized draft laws allowing users to opt out of algorithms.',
  importance_score: 70,
  created_at: '2026-09-23T04:21:10+00:00',
  event_time: '2026-09-23T02:13:52+00:00',
  category: 'Policy',
  entities: ['Australia', 'United States'],
  primary_source: { name: 'BBC News', url: 'https://www.bbc.com/news/articles/x', tier: 'origin' },
  official_source: { name: 'BBC News', url: 'https://www.bbc.com/news/articles/x', tier: 'origin' },
  ingest_source: { name: 'Hacker News', url: 'https://news.ycombinator.com/rss', tier: 'community' },
  article_url: 'https://www.bbc.com/news/articles/x',
};

const OVERVIEW: MarketOverviewData = {
  as_of: '2026-09-24T10:00:00+00:00',
  happening_now: [],
  trending: [],
  biggest: [
    {
      id: 'a7e3c47d-4400-4c99-8b1d-dfe0398e20ae',
      headline: 'Introduction of Claude Opus 5.5 Model',
      summary: 'Anthropic released Claude Opus 5.5.',
      organization: 'Anthropic',
      category: 'Models',
      event_time: '2026-09-22T16:29:00+00:00',
      importance_score: 85,
      importance_label: 'Significant',
      source_count: 2,
      source_label: 'Official source',
      source_name: 'Anthropic',
    },
  ],
  pulse: [{ label: 'Models', week: 8, sources: 6 }],
  players: [],
  ingestion: {
    llm_available: true,
    last_ingested_at: '2026-09-23T04:52:57+00:00',
    sources_enabled: 25,
    sources_failing: 8,
    pending_enrichment: 12,
    enrichment_paused: true,
  },
};

function mockFetch(routes: Record<string, { status?: number; body?: unknown } | Error>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(routes).find((part) => url.includes(part));
    const route = key ? routes[key] : { status: 404, body: {} };
    if (route instanceof Error) throw route;
    return new Response(JSON.stringify(route.body ?? {}), { status: route.status ?? 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('provenance labels', () => {
  it('names each evidence tier honestly', () => {
    expect(evidenceLabel({ tier: 'primary' })).toBe('Official source');
    expect(evidenceLabel({ tier: 'origin' })).toBe('Original article');
    expect(evidenceLabel({ tier: 'secondary' })).toBe('News coverage');
    expect(evidenceLabel({ tier: 'community' })).toBe('Discussion');
    expect(evidenceLabel({ tier: 'secondary', url: 'https://arxiv.org/abs/2609.1' })).toBe('Research paper');
  });

  it('never calls an origin behind an aggregator official', () => {
    expect(evidenceLabel({ tier: 'origin' })).not.toBe('Official source');
  });
});

describe('time', () => {
  it('shows a date, not a fake clock, for date-only feeds', () => {
    expect(hasClockTime('2026-09-22T00:00:00+00:00')).toBe(false);
    expect(formatUtcCardTime('2026-09-22T00:00:00+00:00')).toBe('22 Sep');
    expect(formatUtcCardTime('2026-09-22T16:29:00+00:00')).toBe('4:29 PM');
  });
});

describe('EventCard', () => {
  it('links to the internal event and separately to the original source', () => {
    const markup = html(<EventCard event={EVENT} />);
    expect(markup).toContain(`href="/events/${EVENT.id}"`);
    expect(markup).toContain(EVENT.headline.replace("'", '&#x27;'));
    expect(markup).toContain('Policy');
    expect(markup).toContain('Original article');
    expect(markup).not.toContain('Official source');
    expect(markup).toMatch(/href="https:\/\/www\.bbc\.com\/news\/articles\/x"[^>]*target="_blank"[^>]*rel="noopener noreferrer"/);
  });

  it('does not render an unsafe source URL', () => {
    const markup = html(
      <EventCard event={{ ...EVENT, article_url: 'javascript:alert(1)', official_source: undefined, primary_source: { name: 'X', url: 'javascript:alert(1)', tier: 'secondary' } }} />,
    );
    expect(markup).not.toContain('javascript:');
  });

  it('shows merged coverage and an updated source page, and nothing for a single report', () => {
    const merged = html(<EventCard event={{ ...EVENT, source_count: 3, is_update: true }} />);
    expect(merged).toContain('+2 publishers');
    expect(merged).toContain('Updated');
    const single = html(<EventCard event={{ ...EVENT, source_count: 1, is_update: false }} />);
    expect(single).not.toContain('publisher');
    expect(single).not.toContain('Updated');
  });

  it('dates each card when the list has no day headings', () => {
    expect(html(<EventCard event={EVENT} withDate />)).toContain('23 Sep');
    expect(html(<EventCard event={EVENT} />)).not.toContain('23 Sep');
  });
});

describe('MarketOverview', () => {
  it('shows explicit empty states for Now and Trending', () => {
    const markup = html(<MarketOverview data={OVERVIEW} stale />);
    expect(markup).toContain('No significant development in the last 36 hours.');
    expect(markup).toContain('No category has recent activity from more than one publisher.');
    expect(markup).toContain('Ingestion is not current');
    expect(markup).toContain('Introduction of Claude Opus 5.5 Model');
    expect(markup).toContain('Official source: Anthropic');
  });
});

describe('homepage', () => {
  it('renders the overview, the feed and an honest paused status', async () => {
    mockFetch({
      '/events/overview': { body: OVERVIEW },
      '/events/?scope=week': { body: [EVENT] },
    });
    const markup = html(await Home());
    expect(markup).toContain('What is changing in AI');
    expect(markup).toContain('1 canonical development this week');
    expect(markup).toContain('Enrichment paused');
    expect(markup).toContain('12 new articles are stored');
    expect(markup).not.toContain('>Live<');
    expect(markup).toContain(EVENT.id);
  });

  it('shows an unavailable state, not a crash, when the API is down', async () => {
    mockFetch({ '/events': new Error('ECONNREFUSED') });
    const markup = html(await Home());
    expect(markup).toContain('Intelligence API unavailable');
  });
});

describe('event-not-found (proxy)', () => {
  const request = (id: string) => new NextRequest(`http://localhost:3000/events/${id}`);

  it('rewrites a missing event to a real 404 route', async () => {
    mockFetch({ '/resolve': { status: 404 } });
    const response = await proxy(request('00000000-0000-0000-0000-000000000000'));
    expect(response.headers.get('x-middleware-rewrite')).toContain('/_missing/event');
  });

  it('rewrites a malformed id without calling the API', async () => {
    const fetchMock = mockFetch({});
    const response = await proxy(request('not-a-uuid'));
    expect(response.headers.get('x-middleware-rewrite')).toContain('/_missing/event');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('redirects a merged duplicate to its canonical event', async () => {
    const canonical = 'f1e75e89-1e37-4887-8415-14918cd198eb';
    mockFetch({ '/resolve': { body: { canonical_id: canonical } } });
    const response = await proxy(request('d02d91a5-e88c-4d13-ad58-1a59ebcdda7e'));
    expect(response.status).toBe(308);
    expect(response.headers.get('location')).toContain(`/events/${canonical}`);
  });

  it('passes through when the API is unreachable, so the page can say so', async () => {
    mockFetch({ '/resolve': new Error('ECONNREFUSED') });
    const response = await proxy(request('a7e3c47d-4400-4c99-8b1d-dfe0398e20ae'));
    expect(response.headers.get('x-middleware-rewrite')).toBeNull();
    expect(response.headers.get('x-middleware-next')).toBe('1');
  });
});

describe('player page', () => {
  it('renders a known player with its developments', async () => {
    mockFetch({
      '/events/overview': { body: { ...OVERVIEW, players: [] } },
      'player=anthropic': { body: [EVENT] },
    });
    const markup = html(await PlayerPage({ params: Promise.resolve({ slug: 'anthropic' }) }));
    expect(markup).toContain('Anthropic');
    expect(markup).toContain(`/events/${EVENT.id}`);
  });

  it('is not found for an unknown player', async () => {
    mockFetch({});
    await expect(PlayerPage({ params: Promise.resolve({ slug: 'not-a-player' }) })).rejects.toThrow(
      'NEXT_NOT_FOUND',
    );
  });
});

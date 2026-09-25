# AI Market News: frontend

Next.js 16 (App Router), React 19 and Tailwind CSS 4. Pages are server-rendered from the backend API. Setup for the whole project is in the [root README](../README.md).

```bash
npm ci
npm run dev        # http://localhost:3000
```

The API address comes from `NEXT_PUBLIC_API_BASE_URL` (copy `.env.example` to `.env.local`) and defaults to `http://localhost:8000`.

| Command | |
|---|---|
| `npm test` | Vitest |
| `npm run lint` | ESLint |
| `npx tsc --noEmit` | Typecheck |
| `npm run build` / `npm start` | Production build and server |

| Path | |
|---|---|
| `src/app/(home)/page.tsx` | Homepage |
| `src/app/events/[id]/page.tsx` | Event page |
| `src/app/players/[slug]/page.tsx` | Player page |
| `src/app/admin/sources/page.tsx` | Source health |
| `src/components/` | Cards, rows, overview sections, image frame, header |
| `src/lib/` | API base URL, categories, importance, provenance labels, UTC time formatting, URL sanitizing |
| `src/proxy.ts` | Real 404s for unknown events; redirects merged duplicates to their canonical event |

# Contributing

Thank you for helping. Bug reports, source suggestions and focused pull requests are welcome. Note that the project has no license yet (see the README), so please open an issue to discuss before investing in a large change.

## Before you start

- Read [architecture.md](architecture.md). The product object is the canonical event: one real-world development, with its articles as evidence.
- Keep changes small and in the style of the surrounding code.
- Prefer a simple deterministic rule to a new service, and SQLite to new infrastructure.

## Development setup

See [getting-started.md](getting-started.md). You do not need a provider key to run the tests.

## Pull requests

1. Branch from `main`.
2. Add or update tests for the behaviour you change.
3. Run the checks:

   ```bash
   cd backend && python -m pytest -q
   cd frontend && npm test && npx tsc --noEmit && npm run lint && npm run build
   ```

4. Describe what changed and why, and how you tested it. Include screenshots for UI changes.

## Rules that protect users and costs

- Never commit credentials, `.env` files, databases, logs or screenshots containing private data.
- Do not add code paths that call a paid provider from normal tests. Live checks must be marked `live_openai` / `live_nvidia` and stay opt-in.
- Any new maintenance job that calls a provider must print an estimate first, keep dry-run and apply separate, be reversible, and stop on exhausted quota.
- Never show readers a quote that was not verified against the source text.
- Fetch external URLs only through `app/core/fetcher.py`.

## Suggesting a source

Open an issue with the organization, the feed URL, and whether it is an official, research, news or community source. Feeds must be public RSS or Atom.

## Security issues

Do not open a public issue. See [SECURITY.md](../SECURITY.md).

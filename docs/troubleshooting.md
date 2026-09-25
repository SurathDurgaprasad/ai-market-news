# Troubleshooting

## The homepage says "API unreachable"

The frontend could not reach the backend.

- Is the API running? `curl http://127.0.0.1:8000/api/health`
- Does `NEXT_PUBLIC_API_BASE_URL` (in `frontend/.env.local`) match the API's address? It defaults to `http://localhost:8000`. Restart `npm run dev` after changing it, and rebuild for production.
- Browser requests (images) need the API origin to be reachable from the browser, and the frontend origin to be listed in `CORS_ALLOWED_ORIGINS`.

## "Ingestion paused: no language model is configured"

`/api/health` shows `"llm_mode": "unavailable"`. Set `LLM_PROVIDER` and that provider's key in `backend/.env` (or the environment) and restart the API. For `anthropic` or `bedrock`, also install the SDK (`pip install anthropic` / `boto3`).

## "Enrichment paused: the language model provider is not responding"

The provider timed out, failed or refused requests during a cycle. New articles are stored as pending and retried automatically 15 minutes later. Check:

- `python manage_sources.py llm-usage --hours 1`: the `failed` count and the exception types.
- An `insufficient_quota` error means the provider account has no credit. It is not retried; add credit and pending articles will be processed on a later cycle.
- A rate-limit error clears on its own.

## "Updates delayed"

No new development has been recorded for more than 6 hours. This can simply mean a quiet period. Check the **Sources** page for failing feeds and `/api/health` for the provider state.

## A source is failing

The Sources page shows its last error. Common causes: the feed moved (fix it with `manage_sources.py update --url …`), the site blocks automated clients, or the URL now serves an HTML page instead of a feed. Failing sources back off automatically, up to 4 hours between attempts.

## No images on cards

Images are served by the API at `/api/v1/events/{id}/image`. If a publisher's image cannot be fetched or is not a supported raster format, the card shows a neutral tint instead; the failure is remembered for 6 hours. Deleting `backend/image_cache/` forces a refetch.

## `database is locked`

SQLite allows one writer at a time. Ingestion retries lock contention itself. Avoid running a second API process against the same database file; run CLI commands while the API is running only when they are read-only or dry runs.

## Tests call a real provider or print a key

They should not. Normal runs remove provider keys before the app loads. If you have set `RUN_LIVE_LLM_TESTS=1` in your shell profile, unset it.

## Windows: `DLL load failed … filename or extension is too long`

Python cannot load a native module (Pillow) from a very deep path. Create the virtual environment at a shorter path.

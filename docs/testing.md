# Testing

Every check below runs offline and needs no API key.

## Backend

```bash
cd backend
python -m pytest -q
```

About 650 tests cover the pipeline, deduplication, evidence verification, categories, digests, the API, the scheduler's outage behaviour, SSRF and hostile-input handling, prompt-injection boundaries, log redaction, thumbnails and the cost controls. Tests use an in-memory SQLite database and the deterministic `TestLLMProvider`, or providers with fake clients.

`pytest.ini` sets a 30-second per-test timeout, so a hang fails loudly.

Useful subsets:

```bash
python -m pytest -q tests/test_llm_cost_controls.py tests/test_intelligence_quality.py   # cost controls, categories, digests
python -m pytest -q tests/test_thumbnails.py tests/test_origin_attacks.py                # image endpoint, provenance attacks
python -m pytest -q -k "ssrf or redirect or rebinding or decompression"                  # fetcher hardening
```

Tests for the optional Anthropic and Bedrock SDKs skip when those packages are not installed.

## Frontend

```bash
cd frontend
npm ci
npm test            # Vitest: components, pages, proxy, provenance labels, time handling
npx tsc --noEmit    # typecheck
npm run lint        # ESLint
npm run build       # production build
```

## Live-provider tests (opt-in)

A few tests call a real provider to check behaviour that fakes cannot, such as whether a model resists prompt injection. They are marked `live_openai` or `live_nvidia`, and they are **skipped unless explicitly enabled**:

```bash
RUN_LIVE_LLM_TESTS=1 python -m pytest -q -m live_openai
```

- They spend real quota. Check the provider account first.
- Without `RUN_LIVE_LLM_TESTS=1`, the suite removes provider keys from the environment before the app loads, so no test can reach a provider even if a key is set on your machine.
- Real requests made during tests are recorded in a temporary per-run usage ledger, not in `backend/logs/`.
- Never paste keys into test files, fixtures or logs. Fixture keys in the tests are short fake strings.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

| Job | Runs |
|---|---|
| Backend | `pip install -r requirements.txt`, then `pytest` |
| Frontend | `npm ci`, tests, typecheck, lint, production build |
| Docker | builds the backend image |

CI has no provider secrets, and live-provider tests are skipped there.

# Configuration

The backend reads environment variables, and `backend/.env` if present. `backend/.env.example` lists every setting; copy it to `backend/.env` and fill in what you need. `.env` files are ignored by git.

The frontend reads `frontend/.env.local` (copy `frontend/.env.example`).

## Language-model provider

One provider is active at a time, chosen by `LLM_PROVIDER`.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai`, `nvidia`, `anthropic` or `bedrock` |
| `OPENAI_API_KEY` | — | Required for `openai` |
| `OPENAI_MODEL` | `gpt-4.1` | |
| `NVIDIA_API_KEY` | — | Required for `nvidia` (OpenAI-compatible NIM endpoint) |
| `NVIDIA_MODEL` | `openai/gpt-oss-20b` | |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | |
| `ANTHROPIC_API_KEY` | — | Required for `anthropic`; also `pip install anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_MODEL_ID` | — | Required for `bedrock`; also `pip install boto3` |

If the selected provider has no key, or its SDK is not installed, the API still starts and serves stored developments. `/api/health` reports `"llm_mode": "unavailable"`, ingestion does not run, and the homepage shows that ingestion is paused. The system never substitutes another provider or a fake one.

Keys are never logged: a log filter redacts key shapes, `Authorization` headers and `api_key=` style values from every log record.

## Database

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./ai_platform.db` | SQLite only; relative paths are relative to the directory the API starts in (`backend/`) |

The database and its tables are created on first start. SQLite runs in WAL mode with a 30-second busy timeout, so reads continue while ingestion writes. Back up by copying the `.db` file while the API is stopped.

## Web and scheduling

| Variable | Default | Meaning |
|---|---|---|
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins allowed to call the API. No wildcard. |
| `SCHEDULER_ENABLED` | `1` | `0` serves stored data without fetching sources or calling the provider |

## Files written at runtime

| Variable | Default | Contents |
|---|---|---|
| `LLM_USAGE_LOG` | `backend/logs/llm_usage.jsonl` | One line per provider request: provider, model, operation, subject, tokens, latency, success. Never prompts, responses or keys. |
| `IMAGE_CACHE_DIR` | `backend/image_cache/` | Resized WebP copies of event images. Safe to delete. |

Both locations are ignored by git.

## Frontend

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Where the frontend (server and browser) reaches the API. It is embedded in the browser bundle at build time, so it must be a URL browsers can reach. |

## Development and test only

| Variable | Meaning |
|---|---|
| `TESTING=1` | Deterministic test provider, no scheduler. Set automatically by the test suite. Never set in production. |
| `TEST_MODE=1` | Same, and uses a separate `test.db`. Never set in production. |
| `RUN_LIVE_LLM_TESTS=1` | Allows tests marked `live_openai` / `live_nvidia` to call real providers. See [testing.md](testing.md). |
| `LLM_CREDENTIALS_DISABLED=1` | Set by the test suite: provider keys are not read from the Windows user or machine environment. |

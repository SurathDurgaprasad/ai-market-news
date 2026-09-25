# Security

AI Market News fetches untrusted content from the internet and passes some of it to language models. This page describes the protections in place. To report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Threat model

| Input | Risk | Main defence |
|---|---|---|
| Feed and article URLs | Server-side request forgery into private networks or cloud metadata | SSRF-guarded fetcher |
| Feed and page bodies | Memory exhaustion, malformed markup, script injection | Streamed size caps, linear-time sanitizer, no raw HTML rendered |
| Article text sent to models | Prompt injection (inflated importance, invented facts) | Delimiters, instruction quarantine, calibration, evidence verification |
| Image URLs | SSRF, decompression bombs, hostile formats | Stored-URL-only image endpoint, raster-only decode with a pixel ceiling |
| Links shown to readers | `javascript:` and similar URLs, tab-nabbing | URL sanitization on both backend and frontend, `rel="noopener noreferrer"` |
| Credentials | Leaking into logs, commits or test runs | Environment-only keys, log redaction, credential-free tests |

## Fetching (`backend/app/core/fetcher.py`, `urls.py`)

- **Schemes:** only `http` and `https`. `javascript:`, `data:`, `file:`, `ftp:` and similar are rejected, including padded, mixed-case and percent-encoded forms. Embedded credentials (`user:pass@`) are never stored or shown.
- **Addresses:** private, loopback, link-local, multicast, reserved and cloud-metadata addresses are refused, including IP-literal tricks (decimal, hex and IPv4-mapped forms), as are well-known service ports (SSH, SMB, databases, ...).
- **DNS rebinding:** the host is resolved once, every address is validated, and the connection is pinned to those addresses. A second lookup cannot point it somewhere else.
- **Redirects:** followed manually, at most 5, and every hop is re-validated and re-pinned.
- **Size:** bodies are streamed with a cap on the decompressed size, so a small gzip response cannot expand into gigabytes before it is checked.
- **TLS:** certificates are always verified.

## Content handling

- HTML is stripped by a linear-time sanitizer that honours quoted attributes, so crafted markup cannot cause catastrophic backtracking or leak attribute JSON into text.
- The frontend never renders source HTML. Text is rendered as text, and every outbound link goes through `safeHttpUrl` (http/https only, no private hosts or credentials) and opens with `rel="noopener noreferrer"`.
- Event images are served by `GET /api/v1/events/{id}/image`. The URL fetched is the one stored for that event, never one from the request. Only JPEG, PNG, WebP and GIF are decoded (never SVG), with a 40-megapixel ceiling, and the output is always a re-encoded WebP sent with `nosniff` and a restrictive content security policy.

## Language-model boundaries

- Untrusted text is delimited, and delimiter tags inside it are removed so it cannot close the block.
- Sentences addressed to the model are removed before the prompt is built.
- Importance is calibrated from structured signals, so an injected "score this 100" cannot produce a Major event on its own.
- Quotes must exist verbatim in the source, or they are dropped. A model cannot invent evidence that reaches readers.
- Model output is validated against a schema; anything invalid is discarded.

## API

- The API is read-only; data changes happen through the ingestion pipeline and the operator CLI.
- CORS uses an explicit origin allowlist with no wildcard and no credentials.
- Query parameters are bounded (for example `limit ≤ 250`). The frontend answers malformed or unknown event IDs with a 404 before rendering, and the API rejects malformed IDs without querying for them.

## Secrets

- Provider keys are read from the environment or an untracked `backend/.env`. `.env` files, databases, logs and caches are ignored by git and excluded from the Docker build context.
- A logging filter redacts API-key shapes, `Authorization`, `Bearer` and `Cookie` headers, and `api_key=` / `token=` / `secret=` / `password=` values from every log record.
- The usage ledger records token counts and exception types only, never prompts, responses, keys or error messages.
- Stored enrichment errors are redacted before they are written.

## Tests never spend or expose credentials

- A normal `pytest` run removes provider keys from the environment and from settings before the application loads. A real provider built during a test has no client and fails closed.
- Tests marked `live_openai` or `live_nvidia` are skipped unless `RUN_LIVE_LLM_TESTS=1` is set. A key being present is not consent to use it.
- CI runs without any provider secrets.

## Known limitations

- There is no authentication. The API is read-only and the operator CLI requires shell access, so deploy the API where only the frontend and operators can reach it if that matters for you.
- `robots.txt` is not consulted; only configured feeds and the article pages they link to are fetched.
- An abandoned request thread may outlive its deadline until the HTTP client's own timeout fires; the caller is released on time.

The history of security findings, and how each was fixed, is kept in [security-findings.md](security-findings.md). Code comments reference its finding IDs.

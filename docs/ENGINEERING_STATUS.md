# Engineering Status

Living document tracking the state of the AI World Intelligence Platform
against the engineering/red-team/hardening/productization loop. Updated as
work proceeds. Do not delete history from this file — append and update
statuses in place so the trajectory stays visible.

Status vocabulary used throughout: `VERIFIED`, `PARTIALLY VERIFIED`,
`NOT VERIFIED`, `KNOWN LIMITATION`, `OPEN FINDING`, `FIXED`.

---

## Session log

### 2026-09-21 — Session 1: Phase 0 baseline

**Scope of this session:** repository inspection, architecture mapping,
local version control setup, baseline test/typecheck run, and an initial
pass of manual code reading across the security-relevant modules. This is
the first session of what the operating brief describes as a multi-session
continuous loop — the 22-phase program in the brief is not achievable in a
single sitting on a codebase this size, and this document says explicitly
what has and has not been verified rather than implying completeness.

#### Repository hygiene actions taken
- Initialized a **local-only** git repository (`git init`) at the project
  root. Nothing has been pushed anywhere; no remote is configured. This
  exists purely as a safety net for the many changes this loop will make.
- Added a root `.gitignore` (venvs, `__pycache__`, `*.db*`, logs, env files).
- Removed a nested `.git` inside `frontend/` (a leftover trivial
  `create-next-app` scaffold commit with no history worth preserving) so
  the whole tree is one repository instead of an accidental embedded repo.
- Committed a baseline snapshot (132 files, ~23k lines) capturing the
  repository exactly as inherited, before any behavioral changes.
- **Incident:** while checking whether `NVIDIA_API_KEY` was configured, a
  `env | grep -i nvidia` command printed the live key value into tool
  output instead of just confirming presence. Flagged to the user
  immediately. No further secret values have been or will be printed;
  presence checks now use existence/length only.

#### Baseline verification status

| Area | Status | Notes |
|---|---|---|
| Backend test suite exists and mostly passes | `PARTIALLY VERIFIED` | 354 tests collected. All non-live tests observed passing so far. Full pass/fail count pending — see Open Findings below. |
| Frontend TypeScript (`tsc --noEmit`) | `VERIFIED` | Clean, zero errors, before and after this session's one fix. |
| Frontend ESLint | `FIXED` | One error (`@typescript-eslint/no-explicit-any` + unused import) in `frontend/src/app/admin/sources/page.tsx` fixed by adding a proper `AdminSource` interface matching the backend's `SourceResponse` schema. Two remaining warnings (`<img>` vs `next/image` in `EventCard.tsx` and `events/[id]/page.tsx`) are a considered product/security tradeoff, not a defect — see Open Findings. |
| SQLite is the intentional datastore | `VERIFIED` | `backend/app/core/config.py` hardcodes SQLite and comments explicitly forbid pointing it at Postgres. Matches the operating brief's stated architecture decision. |
| Provider abstraction (NVIDIA / OpenAI / Anthropic / Test / FailClosed) | `VERIFIED` | Read in full: `backend/app/core/providers/llm.py`. Clean `LLMProvider` ABC, per-provider classes, and a `FailClosedLLMProvider` that raises on every call. |
| Production never silently falls back to `TestLLMProvider` | `VERIFIED` (by code reading) | `resolve_llm_mode()` / `get_llm_provider()` return `FailClosedLLMProvider` (fail-closed) when no production provider is configured — it never returns `TestLLMProvider` outside `is_test_runtime()`. Confirmed by reading the logic; not yet exercised with a dedicated adversarial test run in this session. |
| NVIDIA live provider genuinely reachable and exercised | `VERIFIED`, partially | `curl` confirms `https://integrate.api.nvidia.com/v1` is reachable (200, 1.6s) from this environment. Two of the three live-call tests in `test_prompt_injection_semantic.py` (`test_semantic_prompt_injection_importance`, `test_semantic_prompt_injection_fabricate_evidence`) completed and passed against the real NVIDIA endpoint using the real `NVIDIA_API_KEY` present in this environment. The third (`test_semantic_prompt_injection_json_ld`) stalled — see Open Finding NVDA-01. |
| SSRF hardening (`app/core/urls.py`, `app/core/fetcher.py`) | `VERIFIED` (by code reading) | Blocklist covers loopback/private/link-local/multicast/reserved/unspecified, IPv4-mapped IPv6, decimal/hex/short IP literals, dangerous schemes (including percent-encoded), credentials-in-URL, blocked ports. `fetcher.py` additionally resolves DNS once, rejects on any blocked address, and **pins** `socket.getaddrinfo` per-thread so the actual TCP connect cannot be redirected by a second DNS lookup (DNS-rebinding TOCTOU mitigation) — pinning is re-validated independently per redirect hop, capped at 5 hops. This is a genuinely above-average implementation for this attack class. Not yet actively re-attacked in this session (existing test files `test_ssrf_attacks_new.py`, `test_ssrf_redirects.py` exist and were passing in the observed run, but I have not yet written new adversarial cases beyond what's already there — see Phase 2 plan). |
| Evidence grounding / citation verification | `VERIFIED` (by code reading) | `deduplication.py::verify_citations` requires normalized citation text to be an exact contiguous substring of the normalized article (Unicode punctuation normalized first, so smart quotes/dashes can't be used to fake a mismatch either way), rejects sub-15-character citations. `fallback_source_citations` never paraphrases — it only ever copies real sentences already run back through `verify_citations`. |
| Origin/provenance separation (ingest source vs. official source) | `VERIFIED` (by code reading) | `app/core/origin.py`: only promotes to "official source" display when the ingest source is a known aggregator AND the article lives on a different registrable host AND a publisher name was recovered from actual page evidence (`og:site_name` / JSON-LD), never invented from the domain string alone. |
| Importance calibration | `VERIFIED` (by code reading) | `app/core/importance.py` bands scores by `(event_kind, technical_change_scope)` rather than trusting the raw LLM number outright; comments reference a specific past failure mode ("Rubin into Significant") that shaped the current ceiling-clamping rule — evidence this was tuned against a real regression, not written speculatively. |
| Architecture docs match the actual system | `NOT VERIFIED — false` | See Open Finding DOC-01. `docs/ARCHITECTURE.md` and root `docker-compose.yml` describe a PostgreSQL + pgvector + Redis + Celery + OIDC/SAML system. The actual, intentional system is FastAPI + SQLite + APScheduler with no auth layer. This is a real, user-facing documentation defect, not a nitpick — anyone onboarding from `docs/ARCHITECTURE.md` today would set up the wrong stack. |
| `docs/IMPLEMENTATION_STATUS.md` accuracy | `NOT VERIFIED — false` | Describes ingestion/dedup/enrichment as "scaffolded" / "not started". Contradicted by direct code reading: dedup, clustering, entity extraction, evidence verification, SSRF hardening, and the LLM provider abstraction are all real, non-trivial, exercised-by-tests implementations. This file is stale and should be rewritten or removed once a current status doc (this one) supersedes it. |

#### Open findings (Phase 0)

**NVDA-01 — Live-call test can hang indefinitely with no enforced timeout (OPEN, unconfirmed root cause)**
- Area: Testing / LLM provider reliability
- `backend/tests/test_prompt_injection_semantic.py::test_semantic_prompt_injection_json_ld` (a live call to `NVIDIAProvider.classify_event`, same code path as its two sibling tests that passed) ran for >8 minutes with the Python process's cumulative CPU time never increasing past ~0.05s — i.e. it was not doing any work, it was blocked on a socket read that never returned and never hit the `openai.OpenAI(..., timeout=90.0)` timeout that should have bounded it. Killed manually.
- `pytest-timeout` is **not installed** in `venv_312`, so nothing in the current test configuration would have stopped this from hanging a CI run or a developer's machine indefinitely.
- Root cause not yet confirmed — candidates: the 90s httpx timeout not applying to whichever phase of the request stalled, a proxy/keepalive interaction unique to this sandboxed environment, or a genuine upstream stall. Needs isolated reproduction outside pytest (a standalone script with an explicit hard `signal.alarm`/subprocess-level timeout) before concluding anything about the product code.
- Regression/mitigation not yet applied. Planned: (1) add `pytest-timeout` with a per-test ceiling for live-call tests so a stall degrades to a clear failure instead of an indefinite hang; (2) once reproduced in isolation, determine whether `NVIDIAProvider` needs an explicit connect/read timeout split rather than relying on the SDK's single `timeout=` float.

**DOC-01 — Architecture documentation describes a system that does not exist (OPEN)**
- `docs/ARCHITECTURE.md` (PostgreSQL + pgvector + Redis + Celery + OIDC/SAML) and root `docker-compose.yml` (Postgres service with hardcoded `ai_password`, commented-out Celery worker) both describe the pre-SQLite-pivot architecture. The real, intentional architecture (SQLite, no Celery/Redis in the active path, no auth layer) lives only in code comments (`config.py`: *"SQLite is the product database. Do not point this at PostgreSQL."*) and this status doc.
- Not yet fixed. Planned for Phase 20: rewrite `docs/ARCHITECTURE.md` to match reality; either delete `docker-compose.yml` or rewrite it as a single SQLite-backed `backend` + `frontend` compose file with no fabricated services.

**CORS-01 — Wildcard CORS with credentials enabled (OPEN, low confirmed impact so far)**
- `backend/app/main.py`: `allow_origins=["*"]` combined with `allow_credentials=True`, marked with an existing `# TODO: Restrict in production` comment. No cookie/session-based auth exists yet in this codebase (confirmed by absence of any auth module), so the practical exploitability today looks low, but the combination is a known-bad pattern that becomes a real credentialed-CSRF-style hole the moment any cookie auth is added, and some CORS stacks will reflect the literal origin for a wildcard+credentials config regardless. Needs a decision: restrict `allow_origins` to a configured frontend origin (env-driven, matching how `NVIDIA_API_KEY` etc. are already handled) and drop `allow_credentials` unless/until real session auth exists.

**DEAD-01 — `app/core/clustering.py` is unreachable in the running system (OPEN, low severity)**
- Its own docstring says as much: *"NOT called by the primary pipeline, which uses a layered entity + LLM approach instead."* It only activates under `pgvector`, which is never installed/available under the SQLite-only product config. Not a bug, but worth a decision in Phase 17: keep as an explicitly-labeled future upgrade path (fine as-is, arguably already labeled clearly enough) vs. remove to reduce surface area. Leaning toward keep + doc note, pending no other findings change that.

**IMG-01 — Raw `<img>` instead of `next/image` (NOT a defect — documented tradeoff)**
- ESLint flags this in `EventCard.tsx` and `events/[id]/page.tsx`. Not fixing blindly: article/event images come from an open-ended, unbounded set of external source domains (the whole point of the source registry), and `next/image` requires an explicit remote-pattern allowlist per domain, which is incompatible with that design without either a proxy/allowlist mechanism or `unoptimized` mode (which would defeat the point of switching). Leaving as-is; recorded here so it isn't silently "fixed" into something worse later.

#### Not yet started (honest scope statement)
Everything in Phases 2–22 of the operating brief beyond the code-reading
already summarized above: active red-teaming with new adversarial test
cases (SSRF, prompt injection, XSS, evidence fabrication, temporal,
concurrency stress beyond what already exists), performance measurement,
frontend malformed-API-response testing in a live browser, full NVIDIA
live-validation pass, and the documentation rewrite. This session
established the baseline; subsequent sessions continue the loop from here.

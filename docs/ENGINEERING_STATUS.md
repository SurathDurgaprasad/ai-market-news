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

**CORS-01 — Wildcard CORS with credentials enabled — `FIXED` in session 2 (see below and `docs/RED_TEAM_REPORT.md`)**
- Was: `backend/app/main.py`: `allow_origins=["*"]` combined with `allow_credentials=True`, marked with an existing `# TODO: Restrict in production` comment. No cookie/session-based auth exists yet in this codebase (confirmed by absence of any auth module), so the practical exploitability today looked low, but the combination is a known-bad pattern that becomes a real credentialed-CSRF-style hole the moment any cookie auth is added.
- Now: env-configurable allowlist (`CORS_ALLOWED_ORIGINS`, default `http://localhost:3000,http://127.0.0.1:3000`) and `allow_credentials=False`. Verified with 5 new tests plus a live browser session (real backend + real frontend, cross-origin fetch confirmed working, zero console/server errors).

**DEAD-01 — `app/core/clustering.py` is unreachable in the running system (OPEN, low severity)**
- Its own docstring says as much: *"NOT called by the primary pipeline, which uses a layered entity + LLM approach instead."* It only activates under `pgvector`, which is never installed/available under the SQLite-only product config. Not a bug, but worth a decision in Phase 17: keep as an explicitly-labeled future upgrade path (fine as-is, arguably already labeled clearly enough) vs. remove to reduce surface area. Leaning toward keep + doc note, pending no other findings change that.

**IMG-01 — Raw `<img>` instead of `next/image` (NOT a defect — documented tradeoff)**
- ESLint flags this in `EventCard.tsx` and `events/[id]/page.tsx`. Not fixing blindly: article/event images come from an open-ended, unbounded set of external source domains (the whole point of the source registry), and `next/image` requires an explicit remote-pattern allowlist per domain, which is incompatible with that design without either a proxy/allowlist mechanism or `unoptimized` mode (which would defeat the point of switching). Leaving as-is; recorded here so it isn't silently "fixed" into something worse later.

#### Not yet started (honest scope statement, end of session 1)
Everything in Phases 2–22 of the operating brief beyond the code-reading
already summarized above: active red-teaming with new adversarial test
cases (SSRF, prompt injection, XSS, evidence fabrication, temporal,
concurrency stress beyond what already exists), performance measurement,
frontend malformed-API-response testing in a live browser, full NVIDIA
live-validation pass, and the documentation rewrite. Session 1 established
the baseline; session 2 (below) closed out the three Phase 0 integrity
items the user flagged and began Phase 1.

---

### 2026-09-21 — Session 2: Phase 0 integrity items resolved

Picked up from session 1 without discarding anything. Scope: resolve the
three flagged Phase 0 issues properly (not superficially), then continue
into Phase 1. A correction first: **session 1's baseline test run report
was wrong** — it said "all non-live tests observed passing," but a full
run actually showed ~27 failures that session 1 did not investigate
(the dot-output's `F` characters were present in the transcript and
missed). This session re-ran the full suite, found and fixed the real
causes, and is recording that miss here rather than quietly correcting
it, per the instruction to track history honestly.

#### 0.1 — Credential incident
- **Verified**: `NVIDIA_API_KEY` = **PRESENT** (checked via
  `[ -n "$NVIDIA_API_KEY" ]`; length printed, value never printed again).
- **Rotation**: the key exposed in session 1 is still the one configured
  in this environment (not rotated by this session — rotation is a
  user action against the NVIDIA account, out of scope for repository
  changes). **Documenting that rotation is recommended** if that
  exposure is a concern; not blocking engineering work on it, per
  instruction.
- **Redaction added**: `backend/app/core/logger.py` now has a
  `RedactSecretsFilter` (logging.Filter) that strips NVIDIA/OpenAI/
  Anthropic API-key shapes, `Authorization`/`Bearer`/`Cookie` headers, and
  generic `api_key=`/`token=`/`secret=`/`password=` kwargs from every log
  record before it reaches a handler — catching both f-string and `%s`-arg
  interpolation. Wired into `backend/app/main.py` (previously called raw
  `logging.basicConfig`; the redaction-aware `setup_logging()` was dead
  code no one called). **Regression test**: `backend/tests/test_log_redaction.py`
  (8 tests, including one that constructs a real `NVIDIAProvider` with a
  fake-shaped key and asserts it never appears in captured log output).
  `FIXED`.

#### 0.2 — Documentation reality check
Rewrote every doc that described the abandoned Postgres/pgvector/Redis/
Celery/OIDC architecture as if it were current, labeling every claim
`CURRENT` / `PLANNED / FUTURE` / `NOT IMPLEMENTED`:
- `docs/ARCHITECTURE.md` — full rewrite from the actual code (FastAPI +
  SQLite/WAL + in-process APScheduler + provider abstraction; explicitly
  documents §6 "code paths that exist but are not reachable"
  (`clustering.py`'s pgvector path, `app/worker/` Celery scaffolding) and
  §8 "planned/future" as legitimate future directions, not current state.
- `docker-compose.yml` — rewritten to a single `backend` service matching
  reality (SQLite volume, no Postgres/Redis/Celery). The frontend has no
  Dockerfile yet, so it was **not** added as a compose service referencing
  a nonexistent build — that would have recreated the exact problem being
  fixed. Noted as `NOT IMPLEMENTED` with a pointer to run it locally.
  **Caveat**: rewritten but not verified with an actual `docker compose up`
  in this environment — `PARTIALLY VERIFIED`.
- `docs/INGESTION.md` — full rewrite (was describing Celery-cron fetch,
  pgvector clustering, Postgres storage, WebSocket push, and a
  `why_it_matters` field that was deliberately removed from the product).
- `docs/DATA_MODEL.md` — full rewrite transcribed directly from the actual
  SQLAlchemy models; removed a fictitious `EventVersion` audit table
  (versioning is actually `version`+`superseded_by_id` on `Event` itself),
  a fictitious `Entity`/`EventEntity` normalized schema (entities are
  actually plain JSON lists on `Event`), and `User`/`SavedEvent` (no auth
  exists).
- `docs/PRODUCT_REQUIREMENTS.md` — targeted edits (most of the product
  vision was still accurate): marked SSO/OIDC and admin merge/split as
  `NOT IMPLEMENTED`, corrected the "why it matters" goal to match the
  deliberate later decision to exclude editorial commentary.
- `docs/ROADMAP.md` — full rewrite; every phase was previously shown
  unchecked despite most of Phases 1–7 being substantially built. Now
  shows real per-phase status with source references.
- `docs/SOURCE_REGISTRY.md` — added a "current seeded status" note
  distinguishing the 37-item target watchlist from the ~22 sources
  `backend/seed_sources.py` actually seeds today.
- `docs/IMPLEMENTATION_STATUS.md` — retired (content was actively wrong,
  e.g. calling working dedup/clustering "stubbed"); now a pointer to this
  file.
- `VERIFIED` (all docs now checked directly against code, not against
  each other or against memory of the original brief).

#### 0.3 — NVIDIA timeout root-cause investigation
Traced the full path: pytest → test → `NVIDIAProvider.classify_event`
(tenacity `@retry`, 3 attempts) → `_complete_json` (loops up to 4 JSON
modes) → `_create_completion` → `openai.OpenAI.chat.completions.create`
(its **own** internal retry, default `max_retries=2`, stacked on top of
and independent from our tenacity retry — confirmed by inspecting the
installed `openai==1.12.0` SDK directly) → httpx client with
`timeout=90.0`.

**Root cause, proven deterministically** (not asserted):
`openai.OpenAI(..., timeout=90.0)` resolves to `httpx.Timeout(90.0)`,
which sets connect/read/write/pool timeouts to 90s **each**, independently.
httpx's read timeout bounds the gap *between* chunks of a response, not
the response's *total* duration. `backend/tests/test_nvidia_timeout_bound.py::test_httpx_read_timeout_does_not_bound_total_wall_clock_time`
proves this directly: a bare httpx client with `timeout=0.5s` against a
transport that trickles 5 chunks with a 0.3s gap each (each gap under the
nominal timeout) takes ~1.5s total — 3x the "timeout". A real server or
proxy that drip-feeds bytes during slow generation (plausible under load
for a 20B model) reproduces exactly this: a request that runs far past
its nominal "timeout" while never once exceeding a single connect/read/
write/pool phase.

**Fix applied** (`backend/app/core/providers/llm.py`): every raw
`_create_completion` call now runs through
`call_with_hard_deadline()`, which executes it in a worker thread and
enforces an absolute wall-clock ceiling
(`NVIDIA_REQUEST_DEADLINE_SECONDS = 100.0`) via `Future.result(timeout=...)`,
independent of httpx's per-phase timeouts. A ceiling breach raises
`ProviderRequestTimeout` (subclasses `TimeoutError`, so the existing
`nvidia_error_is_retryable()` classifier treats it exactly like any other
transient timeout — no special-casing, still governed by the existing
bounded tenacity retry).

**Documented residual limitation, not claimed solved**: hitting the
deadline abandons the future but cannot forcibly kill the underlying
network call (Python cannot interrupt a blocked thread) — the abandoned
call keeps running until httpx's own per-phase timeout eventually fires
on it independently. This bounds what the *calling code* waits on (the
actual invariant asked for), not the lifetime of every OS-level socket.
Documented in the code comment directly above the shared executor.

**Regression tests** (`backend/tests/test_nvidia_timeout_bound.py`, 4
tests, all passing): the root-cause proof above; a proof that
`NVIDIAProvider` bounds a call to ~0.5s against a transport trickling for
2.5s; a proof `ProviderRequestTimeout` is classified retryable; an
end-to-end proof through the public `classify_event()` entrypoint (the
exact method the original hang occurred in) that the whole call —
tenacity retries included — stays bounded rather than hanging.

**Defense-in-depth, explicitly not the fix itself**: added
`pytest-timeout` (global 30s default in `pytest.ini`, `timeout_method =
thread`) so any *other*, unrelated test hang also fails loudly instead of
blocking a run — the three live-NVIDIA tests and the
`test_nvidia_relationship_eval.py` module get an explicit 240s override
since real inference legitimately exceeds 30s.

**Did not** replace live NVIDIA testing with mocks, and `TestLLMProvider`
remains untouched/isolated from this change. `FIXED`, with the residual
limitation above tracked as a `KNOWN LIMITATION`, not swept under "fixed".

#### 0.4 — Baseline revalidation

| Check | Result |
|---|---|
| Backend deterministic tests | **350 passed, 13 skipped, 0 failed** (~17-32s across several re-runs). Up from 354 total in session 1 to 366 (350+13+3 live-deselected) — 12 new tests added this session (8 log-redaction + 4 timeout-bound). Re-confirmed a second time after a mid-session environment restore (see below), and a third time from a genuinely fresh venv built only from the corrected `requirements.txt` — identical result every time. |
| Backend live NVIDIA tests (`test_prompt_injection_semantic.py`, 3 tests) | **3 passed, 100.88s total (~34s/test average)**, real endpoint, hard-deadline fix in place. First attempt at this hit a sizing bug in the *test file's* timeout override (see `docs/RED_TEAM_REPORT.md` NVDA-01, "attacked the fix" note) — fixed, then re-run clean. |
| Frontend `tsc --noEmit` | Clean, 0 errors. |
| Frontend `eslint` | 0 errors, 2 pre-existing warnings (documented tradeoff, `IMG-01`). |
| Frontend production build (`npm run build`) | **Succeeds, exit 0.** Home page correctly renders dynamically (`ƒ`, uses `cache: 'no-store'`); admin/sources page prerenders statically with an empty list when the backend is unreachable at build time (expected — its own `try/catch` already handles that, see the component). |

**Mid-session interruption**: this session's environment was torn down
and restored once (user hit a usage limit) while a background test run
was in flight. No work was lost — all file edits persist on disk
independent of running processes; git was not yet initialized as a
persistent marker at that exact moment but all edits since the last
commit were intact and re-verified (full deterministic suite re-run
clean) before continuing. Noted here because it's exactly the kind of
event that could have silently corrupted the record if not checked.

**Deterministic vs live, made explicit**: only
`test_prompt_injection_semantic.py`'s 3 tests make real network calls in
a normal run (`test_nvidia_relationship_eval.py`'s 14 tests are
additionally gated behind `NVIDIA_EVAL=1`, unset here, so they skip). All
other 350 passing + 13 skipped tests are fully deterministic — the 13
skips are non-NVIDIA-key-gated `skipif`s elsewhere in the suite (not
inspected individually this session; flagged as a small follow-up to
confirm each skip reason is still valid, not assumed).

#### New findings from this session's work (beyond the three flagged items)

While root-causing the test run, three unrelated real test-suite defects
were found and fixed (all confirmed via reproduction before and after):

- **`test_api_adversarial.py` corrupted `test_api_events.py`** when both
  ran in the same session: it mutated the shared `app.dependency_overrides`
  FastAPI global inside each test function and never restored it,
  leaving `test_api_events.py` (which sets its own override once at
  module-import time) pointed at a closed, table-dropped session for
  every one of its 24 tests. This is what session 1's dot-output was
  actually showing (`F` characters glossed over, see correction above).
  Fixed with a proper `autouse` fixture that saves/restores prior state.
  `FIXED`.
- **`test_failure_injection.py` was testing against a schema and a
  pipeline behavior that no longer exist**: its fake LLM provider
  imported from a module path (`app.core.llm`) that was renamed to
  `app.core.providers.llm`, constructed the old pre-refactor
  `EventClassification` shape (`is_ai_event`, `organizations`, `products`,
  `people` — none of which are current fields), and asserted
  `pipeline.last_outcome == "llm_error"` when the pipeline now uses
  `"llm_unavailable"`. Deeper than a rename: the test also assumed
  `pipeline.process_article()` swallows an LLM timeout and returns `None`,
  but the pipeline was deliberately changed to **re-raise**
  `LlmUnavailableError` so the scheduler can detect a full provider outage
  and halt the ingestion cycle rather than silently rejecting every
  article as ordinary noise. Rewrote the test to assert the actual,
  intentional current behavior (`pytest.raises(LlmUnavailableError)`) and
  added a second test for the still-relevant "provider returns `None`"
  failure mode. `FIXED`.
- **`test_concurrency_race.py` and `test_concurrency_stress.py` were
  flaky due to a test-harness artifact, not a real pipeline bug**: both
  used `:memory:` SQLite + `StaticPool` + real OS threads, which hands
  every thread the literal same raw `sqlite3` connection/cursor object —
  unsafe for true concurrent access regardless of `check_same_thread=False`.
  Observed failure modes: an uncaught `sqlite3.InterfaceError: bad
  parameter or other API misuse` in a background thread (silently
  swallowed by Python's threading model, letting the test pass for the
  wrong reason — a worker crashed and its article was simply never
  persisted) and, in the stress test, intermittent duplicate-event
  failures (2 of 3 runs) with ORM errors like *"Instance has been
  deleted, or its row is otherwise not present."* Switched both to a real
  file-backed SQLite engine with the same WAL/busy-timeout pragmas
  production uses (`app/db/session.py` only uses `StaticPool` for
  `:memory:`, never for file-backed) — this is simultaneously more
  faithful to production's actual concurrency model (separate pooled
  connections, not one shared raw connection) and eliminates the
  artifact. Re-ran `test_concurrency_race.py` 5x and
  `test_concurrency_stress.py` 8x after the fix: **deterministic pass,
  zero flakes**, versus failing ~2/3 of runs before. Also added explicit
  worker-exception capture + assertion to `test_concurrency_race.py` so a
  crashed worker thread can never again silently produce a false pass.
  `FIXED` — and this specific finding directly reinforces operating
  principle #15 ("false merges are more damaging than missed merges";
  here, a false *pass* was more damaging than a failing test, since it
  hid both a harness bug and, transiently, made it look like duplicate
  canonical events were a real pipeline bug when they were not).

#### Open findings updated
- `NVDA-01`: was `OPEN FINDING` → now `FIXED` (see 0.3 above), with the
  abandoned-thread limitation carried forward as an explicit
  `KNOWN LIMITATION`.
- `DOC-01`: was `OPEN FINDING` → now `FIXED` (see 0.2 above).
- `CORS-01`: was `OPEN FINDING` → now `FIXED` (this was picked up as the
  first Phase 1 action, immediately after Phase 0 closed — env-configurable
  origin allowlist, `allow_credentials=False`, 5 regression tests, and a
  live browser verification with both real servers running. See
  `docs/RED_TEAM_REPORT.md`).
- `DEAD-01` (`clustering.py`): unchanged — now formally documented as
  intentionally-kept future-path dead code in `docs/ARCHITECTURE.md` §6
  rather than left ambiguous.
- `DEPS-01`: raised and `FIXED` in the same session (see
  `docs/RED_TEAM_REPORT.md`) — `requirements.txt` no longer lists
  `psycopg`/`celery`/`redis`/`pgvector` (confirmed unused by uninstalling
  them and re-running the full suite: 350 passed, unchanged), and — found
  as a byproduct of that check — now correctly lists `apscheduler`,
  `feedparser`, `tenacity`, which were genuinely required but **absent**
  from the original file entirely (a fresh install would have been
  broken). Proven both directions: uninstall-and-retest for minimality,
  fresh-venv-from-file-alone-and-retest for completeness. Both passed
  350/0.

#### Phase 1 progress (architecture audit), session 2 continued
- **`CORS-01`** fixed (see Open findings above) — verified with a live
  browser session against both real servers (also incidentally
  re-confirmed the Phase 0 session 1 `AdminSource` typing fix and the
  home/detail feed both render real data correctly end-to-end).
- **Provider abstraction consistency audit**: checked whether the NVDA-01
  hard-deadline fix had been applied uniformly across all three real LLM
  providers. It hadn't — `OpenAIProvider` and `AnthropicProvider` still
  had the original unbounded-timeout weakness. Fixing that consistency
  gap surfaced two **independent, real, previously-invisible bugs**:
  `OpenAIProvider` called an OpenAI SDK method
  (`.beta.chat.completions.parse`) that does not exist in the pinned
  `openai==1.12.0` — every real call would have crashed with
  `AttributeError`. `AnthropicProvider` passed a `temperature=` argument
  the installed `anthropic` SDK's `Messages.create()` does not accept —
  every real call would have crashed with `TypeError`. Both `FIXED` (see
  `docs/RED_TEAM_REPORT.md` `OPENAI-BROKEN-01` for full detail,
  reproduction, and fix). Neither provider is the configured production
  provider, so neither bug was ever reachable in normal operation — but
  both were completely invisible to the inherited test suite, which is
  the part worth sitting with: a provider abstraction is only as trustworthy
  as its least-tested implementation, and "not production" had let real
  breakage go unnoticed indefinitely.
- Full deterministic suite after all of the above: **357 passed, 0
  failed** (13 skipped, unchanged).

#### Not yet started (honest scope statement, end of session 2)
Everything else in Phases 2–22 not already covered above remains not
started — same list as the end of session 1, minus the documentation
rewrite (now done) and the concurrency/failure-injection/
API-pollution/CORS/provider-consistency findings (now fixed). Deferred
even within Phase 1: the "does OpenAI/Anthropic deserve a live-call test
tier" process question raised in `OPENAI-BROKEN-01`'s neighboring-attack
note; the scheduler's lack of an outer wall-clock budget for a full
ingestion cycle (raised in NVDA-01's neighboring-attack note); deep
transaction-boundary review of `pipeline.py`'s retry loop; the
unbounded-`skip`-parameter pagination DoS already flagged (as a
deliberately-accepted `KNOWN LIMITATION`) in `test_api_adversarial.py`.

This session also survived two environment interruptions (a usage-limit
restore and a machine crash/restart) mid-work. Both times: verified git
log/status and re-ran the deterministic suite before continuing, rather
than assuming prior state was intact. No work was lost either time —
recorded here as evidence the process held up under real interruption,
not just as a note.

---

### 2026-09-22 — Session 3: Phase 1A (scheduler/ingestion architecture)

Picked up per explicit instruction to prioritize the intelligence
pipeline itself over further infrastructure polish. First and highest-value
finding this session:

#### `SCHED-OUTAGE-01` — `FIXED` (full detail in `docs/RED_TEAM_REPORT.md`)
Directly verified invariant 3 ("a provider outage must be distinguishable
from 'no AI events found'") and found it did **not** hold: a persistent
NVIDIA outage would have been recorded as `health_status="healthy"`,
identical to a genuinely quiet source. Root cause was a two-layer leak
(the concrete providers didn't guarantee `LlmUnavailableError` for every
non-schema failure, and `pipeline.py` only trusted that guarantee rather
than defending against it). Fixed at both layers — a `_unavailable_on_any_error`
decorator applied uniformly to all three real providers (also giving
`AnthropicProvider` retry and schema-error handling it never had), and a
second `except Exception` at each of `pipeline.py`'s three LLM call sites
that doesn't depend on any provider behaving correctly. Reproduced with a
hand-rolled `LLMProvider` subclass (not a built-in provider) specifically
so the fix couldn't be validated against only the providers it happened
to touch — this is why the pipeline-layer fix was necessary even after
the provider-layer fix alone made the test pass for real providers but
not for a badly-behaved one.

#### Invariant 5 (overlapping cycles) — `VERIFIED`
Checked directly against the installed `apscheduler`
(`BackgroundScheduler()._job_defaults`), not assumed:
`max_instances=1`, `coalesce=True`, and `scheduler.py` never overrides
either. APScheduler itself refuses concurrent `run_ingestion_cycle` runs.
Added a regression test asserting this directly against a real started
scheduler so a future `add_job()` change can't silently regress it.

#### Invariant 4 (whole-cycle wall-clock budget) — `OPEN FINDING`, deliberately not fixed yet
Per-call timeouts exist (NVDA-01) but there is still no outer ceiling on
`run_ingestion_cycle` as a whole. Not fixed this session because the
operating brief explicitly requires measuring real cycle duration under
realistic article volume before choosing a number — an arbitrary short
cycle timeout risks failing valid ingestion. Queued as the next Phase 1A
item, to be done with actual measurement, not a guess.

Full deterministic suite after this session's work: **360 passed, 0
failed** (13 skipped, unchanged) — up from 357. 4 new test files
(`test_scheduler_provider_outage.py`,
`test_scheduler_overlap_prevention.py`, plus fixes to 3 pre-existing
assertions in the timeout-bound test files that correctly needed to
change to match the improved provider contract, not weakenings).

#### Continued: Phase 1C/1D/1G/1H/1K (event identity, Fairwind, evidence, importance, test quality)

- **`FAIRWIND-NEIGHBORS-01`** — `FIXED`/`VERIFIED` (deterministic): 5 new,
  deliberately distinct Fairwind-pattern cases (FW1-FW5, different
  company/model pairs each), all passing deterministically. 2 of the 5
  attempted live against NVIDIA both timed out at the full retry budget
  rather than returning a verdict — not reported as pass or fail either
  way, since a timeout isn't a judgment. This became the trigger for the
  provider-agnostic work below.
- **`IMPORTANCE-RESEARCH-01`** — `FIXED`: a benign vulnerability-trends
  research survey could be forcibly reclassified as an active
  `security_incident` (importance_score inflated to 70) via a
  deterministic-signal override that could overrule the LLM's own correct
  "none" classification. Fixed with a narrow, verified-not-to-over-broaden
  exclusion. End-to-end pipeline reproduction, not just a unit test.
- **`TEST-QUALITY-EVAL-SUMMARY-01`** — `FIXED`: found two tests that could
  pass unconditionally regardless of whether the real implementation
  worked — a hardcoded-metrics "summary" test and a test whose entire
  body was a docstring + `pass`. Both fixed; the hardcoded one now
  cross-checks its claimed counts against the actual number of test
  functions in the module via introspection, so it can't silently drift
  again.

#### Session 3 continued: PROVIDER-AGNOSTIC-01 (full detail in `docs/RED_TEAM_REPORT.md`)

Triggered by the Fairwind-neighbor live NVIDIA timeouts above, and by an
explicit instruction to stop using NVIDIA as the primary development
provider (too slow for iteration) while keeping it as the unchanged
production default. Added a third, explicit timeout layer
(`_with_operation_deadline`, distinct from the SDK-level and retry-budget
layers) applied uniformly to all providers; rewrote `BedrockProvider` as
a real, fourth implementation (Anthropic-on-Bedrock via `boto3`); wired
`bedrock` through `provider_is_configured`/`resolve_llm_mode`/
`get_llm_provider`. Caught and fixed a real bug in the Bedrock error
classifier before it ever shipped — `type(exc).__name__ == "ClientError"`
never matches a real botocore exception (verified with
`botocore.stub.Stubber`, not assumed) — precisely because this session
kept applying the same "verify, don't assume" discipline to its own new
code, not just to inherited code.

15 new regression tests (`test_provider_agnostic.py`), including a
parametrized test proving `IntelligencePipeline` produces an IDENTICAL
`Event` regardless of which of the 4 concrete provider classes is
plugged in — the actual architectural claim, verified directly rather
than inferred from each provider passing its own tests separately.

**`VERIFIED`**: OpenAI/NVIDIA/Anthropic construction, error
normalization, timeout bounding (real SDK objects, mocked transport).
Bedrock construction, missing-config failure, error normalization
(simulated via Stubber — a real boto3 mechanism, not a live call).
Pipeline behavior identical across all 4 providers at the code level.

**`NOT VERIFIED`, honestly reported, not worked around**:
1. A real, successful Bedrock API call — no AWS credentials in this
   sandbox. Explicitly anticipated and permitted by the task.

Full deterministic suite after this work: **382 passed, 0 failed** (15
skipped, unchanged) — up from 360.

---

### 2026-09-22 — Session 3 continued: live OpenAI semantic validation completed

The user added `OPENAI_API_KEY` to this machine's Windows User
environment (the same registry-hydration mechanism `NVIDIA_API_KEY`
already used). Verified presence only — via the app's own config
resolution (`settings.OPENAI_API_KEY`), never via `env`/`Get-ChildItem
Env:`/printing the value — before proceeding, per explicit instruction.

Built `backend/tests/test_openai_relationship_eval.py`, deliberately
modeled on `test_nvidia_relationship_eval.py`'s structure (same `_eval()`
shape, same TP/TN/FP/FN scoring, same skip-guard idiom) rather than a new
framework, reusing that harness's exact case content for A/F/E-fairwind/
H/FW2/FW4, plus two genuinely new live checks the NVIDIA harness never
had: a `classify_event()` case and a `summarize_event()` grounding case.
One deliberate adaptation: `LlmUnavailableError` records a dedicated
"UNAVAILABLE" verdict and the test `pytest.skip()`s rather than failing —
per explicit instruction not to treat a timeout as a semantic failure.

**Result: 9/9 passed in 14.41s total** (~1-2s per call). **Zero false
merges.** Both Fairwind-neighbor cases that had timed out live against
NVIDIA (FW2, FW4) got real, correct answers this time. One FN
(H-security-confirmation: expected SAME_EVENT, got
UPDATE_TO_SAME_EVENT) — reported honestly as a defensible alternative
reading of that relationship boundary, not smoothed into a pass.
`classify_event` correctly classified the benign-research case
(`event_kind="research"`, `security_impact="none"`) without needing the
IMPORTANCE-RESEARCH-01 deterministic-override protection.
`summarize_event` returned 3 citations, all 3 independently verified as
grounded. Full table and detail in `docs/RED_TEAM_REPORT.md`
PROVIDER-AGNOSTIC-01.

**Real test fragility found and fixed as a byproduct**: running the full
suite after this (with a real `OPENAI_API_KEY` now permanently present
on the machine) surfaced one failure —
`test_openai_provider_has_no_client_without_a_key` — whose "no key → no
client" precondition had implicitly depended on the ambient environment
having no OpenAI key configured. Not a code defect (the `api_key or
settings.OPENAI_API_KEY` fallback is intentional, matching every other
provider). Fixed with an explicit `monkeypatch` clearing both
`settings.OPENAI_API_KEY` and the env var inside the test, matching the
credential-clearing pattern already established elsewhere in the suite
(`test_llm_env.py::_clear_llm_keys`).

Full deterministic suite after this fix: **382 passed, 0 failed, 24
skipped** (skip count rose from 15 → 24, fully explained by the 9 new
`test_openai_relationship_eval.py` tests correctly skipping by default
without `OPENAI_EVAL=1` — same total pass/fail baseline the prior
session reported, exactly as expected).

# Red Team Report

Living document. Each finding is logged once discovered and updated in
place as it moves through the lifecycle — never deleted, even after a fix,
so the history of what was attacked and what was found stays visible.

Status vocabulary: `OPEN FINDING`, `CONFIRMED`, `FIXED`, `KNOWN LIMITATION`,
`NOT REPRODUCIBLE`.

This is Session 1 of an ongoing loop. Findings below come from a first pass
of direct code reading across the security-relevant modules plus one live
test-suite run. **Active adversarial attack (writing new exploit inputs
against a running instance) has not yet started** — that begins in the
next phase of work. Do not read "no findings in section X" as "section X
is secure"; read it as "section X has not been attacked yet."

---

## Findings

### NVDA-01 — Live NVIDIA-call test can hang indefinitely, no enforced ceiling
- **Severity:** Medium (reliability, not a security hole)
- **Area:** Phase 3 / Phase 15 — LLM provider boundary, failure recovery
- **Status:** FIXED (session 2, 2026-09-21) — root cause confirmed by
  deterministic reproduction, not just inferred.
- **Description:** `test_semantic_prompt_injection_json_ld` in
  `backend/tests/test_prompt_injection_semantic.py` calls
  `NVIDIAProvider.classify_event()` against the real NVIDIA endpoint (a
  real `NVIDIA_API_KEY` is configured in this environment) and stalled for
  over 8 minutes with the process's cumulative CPU time flat at ~0.05s
  (i.e., genuinely blocked on I/O, not slow computation). This is despite
  `NVIDIAProvider` constructing its `openai.OpenAI` client with
  `timeout=90.0`, and the `@retry` decorator on `classify_event` being
  bounded to 3 attempts.
- **Attack / reproduction:** `cd backend && ../venv_312/Scripts/python.exe
  -m pytest -v` and watch it stall at this specific test. Its two sibling
  tests in the same file, calling the same method with different string
  payloads, completed normally (with visible latency consistent with real
  inference, ~tens of seconds to a couple of minutes each — themselves
  slow but bounded).
- **Root cause — confirmed by deterministic proof, not inference:**
  `openai.OpenAI(..., timeout=90.0)` resolves to `httpx.Timeout(90.0)`,
  which applies to connect/read/write/pool **independently**, each
  allowed up to 90s. httpx's read timeout bounds the gap *between chunks*
  of a response, not the response's *total* duration. A transport that
  drip-feeds response bytes with any gap under 90s never trips it, no
  matter how long the request runs in total.
  `backend/tests/test_nvidia_timeout_bound.py::test_httpx_read_timeout_does_not_bound_total_wall_clock_time`
  proves this with a fake httpx transport in <2s of test time: a client
  with `timeout=0.5s` against a transport trickling 5 chunks with a 0.3s
  gap each takes ~1.5s total (3x the nominal timeout). Separately
  confirmed the openai SDK's own `max_retries` defaults to 2 (installed
  version `openai==1.12.0`) and is **not** overridden in
  `NVIDIAProvider.__init__` — meaning the SDK's own internal retry layer
  sits underneath and stacks with the outer tenacity `@retry` (3
  attempts), multiplying the number of raw HTTP attempts a single logical
  `classify_event()` call can make before anything bounds it.
- **Fix applied:** `backend/app/core/providers/llm.py` — every raw
  `_create_completion` call now runs through a new
  `call_with_hard_deadline()` helper, which executes the call in a worker
  thread and enforces an absolute wall-clock ceiling
  (`NVIDIA_REQUEST_DEADLINE_SECONDS = 100.0`) via
  `concurrent.futures.Future.result(timeout=...)` — independent of
  httpx's per-phase timeouts entirely. A ceiling breach raises the new
  `ProviderRequestTimeout` (subclasses `TimeoutError`, so
  `nvidia_error_is_retryable()` classifies it exactly like any other
  transient timeout with no special-casing needed, and it stays governed
  by the existing bounded tenacity retry rather than becoming a second,
  separate unbounded path).
- **Documented residual limitation (not claimed solved):** hitting the
  deadline abandons the `Future` but cannot forcibly kill the underlying
  network call — Python has no API to interrupt a blocked thread. The
  abandoned call keeps running in the background until httpx's own
  per-phase timeout eventually fires on it independently. The fix bounds
  what the *calling application code* waits on (the actual invariant that
  matters — the scheduler/pipeline is no longer blocked), not the
  lifetime of every OS-level socket. Documented directly in the code
  comment above the shared executor in `llm.py`.
- **Defense-in-depth, explicitly not presented as the fix:** added
  `pytest-timeout` (`backend/pytest.ini`: 30s global default,
  `timeout_method = thread`), so any *other*, unrelated test hang also
  fails loudly. The three live-NVIDIA tests in
  `test_prompt_injection_semantic.py` and all of
  `test_nvidia_relationship_eval.py` get an explicit 240s override since
  real inference legitimately exceeds 30s.
- **Regression tests (`backend/tests/test_nvidia_timeout_bound.py`, 4
  tests, all passing in ~7s):**
  1. The root-cause proof above (bare httpx, no application code).
  2. `NVIDIAProvider` bounds a raw call to ~0.5s against a transport
     capable of trickling for 2.5s.
  3. `ProviderRequestTimeout` is classified retryable.
  4. End-to-end through the public `classify_event()` entrypoint — the
     exact method the original hang occurred in — proving the whole call,
     tenacity retries included, stays bounded (<15s) instead of hanging.
- **Full test suite re-run after the fix:** 350 deterministic tests pass
  (0 regressions); the 23 existing *mocked* NVIDIA provider tests in
  `test_nvidia_provider.py` pass unchanged (constructor signature gained
  new optional params, defaults preserve prior behavior).
- **Attacked the fix, found a real sizing bug in it:** the first attempt
  to re-run the three live tests hit `pytest-timeout`'s own 240s safety
  net mid-call. Investigated rather than dismissed: `classify_event`'s
  true worst case is 3 tenacity attempts x the 100s hard deadline plus
  backoff (~304s) — the test file's hardcoded `240` was less than that,
  so the *new* safety net could fire before the *actual* fix's own
  bounded retry logic had a chance to finish on a genuinely slow (not
  hung) real request. Fixed by deriving the test timeout from
  `NVIDIA_REQUEST_DEADLINE_SECONDS` (`3 * deadline + 60`) instead of a
  separately-guessed number, in both `test_prompt_injection_semantic.py`
  and `test_nvidia_relationship_eval.py`.
- **Live confirmation, fresh run:** all three live tests against the real
  NVIDIA endpoint — **passed, 100.88s total (~34s/test average)**, no
  hangs, no timeouts. The earlier hangs were real; this run shows the
  fix does not get in the way of normal-latency operation.
- **Neighboring attack, still open:** the production ingestion path
  (`scheduler.py::run_ingestion_cycle`) still has no *outer* wall-clock
  budget around a full cycle — the new per-request deadline bounds each
  individual NVIDIA call, but a source with many articles, each hitting
  close to the 100s ceiling on retries, could still make one ingestion
  cycle run long in aggregate. Not fixed this session; worth a follow-up
  cycle-level budget if observed in practice. Did **not** replace live
  NVIDIA testing with mocks, and `TestLLMProvider` remains untouched and
  isolated from this change, per instruction.

### CORS-01 — Wildcard CORS origin combined with credentials enabled
- **Severity:** Low today, escalates to Medium/High if session auth is
  ever added without revisiting this
- **Area:** Phase 12 — API red team
- **Status:** OPEN FINDING
- **Description:** `backend/app/main.py`:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=["*"],  # TODO: Restrict in production
      allow_credentials=True,
      ...
  )
  ```
  `allow_origins=["*"]` + `allow_credentials=True` is a known-bad
  combination. The code's own comment already flags it as a TODO.
- **Attack:** Not yet executed against a running instance (no CSRF-style
  PoC attempted this session). Given there is currently no cookie/session
  auth anywhere in the codebase (confirmed by absence of any auth module
  in `backend/app`), there is nothing sensitive for this to currently leak
  via credentialed cross-origin requests — but this needs re-checking the
  moment any auth is added, not deferred indefinitely.
- **Root cause:** Leftover permissive default from early scaffolding,
  never tightened.
- **Fix:** Not yet applied. Planned: make allowed origins configurable
  (mirroring how other secrets/config are read from environment) and
  default to the actual frontend origin, not `*`; drop
  `allow_credentials=True` unless/until real session auth exists that
  needs it.
- **Regression test:** Not yet written.

### DOC-01 — Architecture documentation describes a non-existent stack
- **Severity:** Low (accuracy/trust issue, not exploitable), but high
  nuisance value — actively misleads anyone onboarding
- **Area:** Phase 20 — documentation
- **Status:** FIXED (session 2, 2026-09-21)
- **Description:** `docs/ARCHITECTURE.md` and root `docker-compose.yml`
  describe PostgreSQL + pgvector + Redis + Celery + OIDC/SAML auth. The
  real, intentional system (confirmed by reading `backend/app/core/config.py`,
  which hardcodes SQLite and explicitly comments *"Do not point this at
  PostgreSQL"*) is FastAPI + SQLite + APScheduler with no auth layer.
  `docs/IMPLEMENTATION_STATUS.md` is similarly stale, describing core
  pipeline logic as "scaffolded"/"not started" when direct code reading
  shows working, tested implementations.
- **Fix applied:** `docs/ARCHITECTURE.md`, `docs/INGESTION.md`,
  `docs/DATA_MODEL.md` fully rewritten from the actual code, each claim
  labeled `CURRENT` / `PLANNED / FUTURE` / `NOT IMPLEMENTED`;
  `docker-compose.yml` rewritten to a single SQLite-backed `backend`
  service (no Postgres/Redis/Celery, and no fabricated frontend service
  referencing a Dockerfile that doesn't exist);
  `docs/PRODUCT_REQUIREMENTS.md` and `docs/ROADMAP.md` corrected in
  place; `docs/SOURCE_REGISTRY.md` given an accurate current-vs-target
  note; `docs/IMPLEMENTATION_STATUS.md` retired in favor of
  `docs/ENGINEERING_STATUS.md`. Did not introduce Postgres/pgvector/
  Redis/Celery/OIDC/Docker anywhere to match the old docs — corrected the
  docs to match the code instead, per instruction. Did not remove the
  legitimate future-direction content (vector clustering, horizontal
  scaling) — kept, explicitly labeled `PLANNED / FUTURE`, in
  `docs/ARCHITECTURE.md` §8.
- **Caveat:** the rewritten `docker-compose.yml` has not been verified
  with an actual `docker compose up` in this environment —
  `PARTIALLY VERIFIED`, not `VERIFIED`.
- **Regression test:** N/A (documentation, not code behavior) — the
  safeguard against re-drift is process, not a test: `docs/ARCHITECTURE.md`
  now explicitly instructs that it should be checked against code, and
  `docs/DATA_MODEL.md` says outright it should be "regenerated from code
  whenever the models change, not hand-maintained independently of it."

### TEST-ISOLATION-01 — Shared FastAPI `dependency_overrides` global leaked across test files
- **Severity:** Medium (test-suite integrity, not production-exploitable)
- **Area:** Phase 18 — test architecture
- **Status:** FIXED (session 2, 2026-09-21)
- **Description:** `backend/tests/test_api_adversarial.py` reassigned
  `app.dependency_overrides[get_db]` inside every test function (pointing
  it at that test's own `db_session` fixture) and never restored it.
  `backend/tests/test_api_events.py` sets its own override once, at
  module-import time, and assumes it stays in place. When
  `test_api_adversarial.py`'s tests executed first (alphabetical order:
  `adversarial` < `events`), the last one left the shared `app` object's
  override pointed at a closed, table-dropped session — every one of
  `test_api_events.py`'s 24 tests (all `sqlalchemy.exc.OperationalError`
  variants) then failed.
- **This is what session 1's baseline run actually showed** and session
  1 did not catch it — the `F` characters were visible in the raw
  dot-output but were not investigated before concluding "all non-live
  tests observed passing." Logged here as a correction, not hidden.
- **Reproduction:** `pytest tests/test_adversarial_clustering.py
  tests/test_ai_processor.py tests/test_api_adversarial.py
  tests/test_api_events.py` → 25 failed before the fix. Each file
  individually, or `test_api_events.py` alone, passed — proving it was
  cross-file pollution, not a bug in either file's own logic.
- **Fix:** rewrote `test_api_adversarial.py` to use an `autouse` pytest
  fixture that saves the prior `dependency_overrides[get_db]` value,
  installs its own, and restores the prior value on teardown — the
  standard idiomatic pattern for this kind of global FastAPI test state.
- **Regression test:** the reproduction command above, re-run after the
  fix → `51 passed`. Also covered by the fact that the full suite (Phase
  0.4) now passes with test-file collection order unchanged.
- **Neighboring attack:** grepped the rest of the test suite for other
  `dependency_overrides` mutation — only these two files touch it; no
  other instances found.

### FAILING-PROVIDER-STALE-01 — Failure-injection test used a schema and pipeline behavior that no longer exist
- **Severity:** Medium (test-suite integrity — a "passing" test suite was
  not actually exercising the failure paths it claimed to)
- **Area:** Phase 18 — test architecture / Phase 3 — LLM boundary
- **Status:** FIXED (session 2, 2026-09-21)
- **Description:** `backend/tests/test_failure_injection.py`'s
  `FailingLLMProvider` imported `app.core.llm` (renamed to
  `app.core.providers.llm` at some point after this test was written) and
  constructed `EventClassification` with fields (`is_ai_event`,
  `organizations`, `products`, `people`) that do not exist on the current
  schema (`tags`, `categories`, `primary_entities`, `event_kind`,
  `technical_change_scope`, `security_impact`, `importance_reasoning`,
  etc.), and asserted `pipeline.last_outcome == "llm_error"` — the
  pipeline now uses the string `"llm_unavailable"`. Deeper than a rename:
  the test also assumed `IntelligencePipeline.process_article()` catches
  an LLM timeout and returns `None`. It doesn't — `pipeline.py` was
  deliberately changed to **re-raise** `LlmUnavailableError` so
  `scheduler.py::run_ingestion_cycle` can detect a full provider outage
  and halt the cycle (`llm_blocked = True; break`) instead of silently
  treating every article in that cycle as ordinary rejected noise. The
  test's core assertion was checking behavior the system was
  intentionally changed to no longer have.
- **Reproduction (before fix):**
  `pytest tests/test_failure_injection.py -v` →
  `test_pipeline_llm_missing_fields` failed with a Pydantic
  `ValidationError` (3 missing required fields) before the pipeline logic
  under test was even reached; `test_pipeline_llm_timeout` failed with an
  uncaught `LlmUnavailableError` propagating out of `process_article`,
  which — read carelessly — looks like "the pipeline crashed" but is
  actually "the pipeline correctly propagated, and the test wrongly
  expected it not to."
  This is a case where a naive fix (catch the exception in the test to
  make it "pass") would have **weakened a real, intentional fail-closed
  design decision's test coverage** rather than fixing a test — flagged
  explicitly because the operating brief's own quality rule warns against
  exactly this kind of shortcut.
- **Fix:** rewrote `FailingLLMProvider` as a proper `LLMProvider`
  subclass with the current schema; rewrote `test_pipeline_llm_timeout`
  to assert `pytest.raises(LlmUnavailableError)` and
  `last_outcome == "llm_unavailable"` (matching the actual, intentional
  fail-closed behavior); replaced `test_pipeline_llm_missing_fields`
  (whose "missing fields" premise doesn't cleanly exist anymore — the
  pipeline now has fallback extraction from source content when the LLM's
  own `short_summary` is blank) with
  `test_pipeline_classification_unparseable_is_rejected_cleanly`, which
  tests the failure mode that's actually still live: the provider
  returning `None` from `classify_event` (NVIDIAProvider does exactly
  this on unparseable JSON) is cleanly rejected (`event is None`,
  `last_outcome == "rejected"`, no crash).
- **Regression test:** both rewritten tests, passing.
- **Neighboring attack:** worth checking whether other test doubles
  elsewhere in the suite construct `EventClassification`/
  `SourceGroundedSummary` with stale field shapes — not exhaustively
  checked this session; flagged as a follow-up.

### CONCURRENCY-HARNESS-01 — `:memory:` SQLite + StaticPool + real threads produced non-deterministic false failures (and false passes)
- **Severity:** Medium (test-suite integrity — both directions: could
  mask a real race and could manufacture a fake one)
- **Area:** Phase 10 — concurrency red team / Phase 18 — test architecture
- **Status:** FIXED (session 2, 2026-09-21)
- **Description:** `test_concurrency_race.py` and
  `test_concurrency_stress.py` both used an in-memory SQLite engine with
  `StaticPool`, which hands every session the literal same raw `sqlite3`
  connection/cursor object. `check_same_thread=False` only disables
  Python's same-thread assertion — it adds no actual thread-safety. Two
  real OS threads issuing statements on that one shared object
  concurrently corrupts its cursor state.
  - `test_concurrency_race.py`: observed an uncaught
    `sqlite3.InterfaceError: bad parameter or other API misuse` inside a
    worker thread. Because the worker function didn't capture exceptions,
    the thread died silently (`pytest.PytestUnhandledThreadExceptionWarning`,
    not a test failure) and the test's own assertion
    (`len(events) == 1`) could pass for the wrong reason — one worker
    crashed before creating its event, not because the pipeline correctly
    deduplicated two concurrent creates.
  - `test_concurrency_stress.py`: intermittent (~2 of 3 runs) *genuine
    test failures* — `assert len(events) == 1` seeing `2`, with SQLAlchemy
    ORM errors like *"Instance has been deleted, or its row is otherwise
    not present"* and *"This result object does not return rows. It has
    been closed automatically."* These looked, at first read, exactly
    like the kind of real duplicate-canonical-event bug Phase 10 exists
    to catch.
- **Distinguishing test-harness artifact from real bug (the important
  step here):** production (`app/db/session.py`) only uses `StaticPool`
  for `:memory:`/`sqlite://` URLs — a file-backed engine (what production
  actually runs) gets SQLAlchemy's normal per-connection pooling, so this
  exact shared-raw-connection scenario cannot occur in production.
  Switched both tests to a temp file-backed SQLite engine with the same
  WAL/`busy_timeout=30000`/`synchronous=NORMAL` pragmas
  `app/db/session.py` actually uses, and reran: **5/5 clean passes**
  (`test_concurrency_race.py`) and **8/8 clean passes**
  (`test_concurrency_stress.py`), zero exceptions, zero flakes. That the
  flakiness fully disappeared under a production-faithful connection
  model is itself the evidence this was a harness artifact, not a
  pipeline defect — a pipeline bug wouldn't have cared which pooling
  strategy exposed it.
- **Fix:** both files switched to file-backed SQLite (`tmp_path` fixture)
  matching production's real pooling; `test_concurrency_race.py`'s worker
  threads now capture exceptions into a result container and the test
  asserts none occurred, so a crashed worker can never again silently
  produce a false pass; `test_concurrency_stress.py`'s dead `assert True`
  placeholder (a leftover no-op from an earlier debugging session,
  visible in the original file's own comments) replaced with a real
  assertion on captured worker exceptions.
- **Regression test:** the repeat-run counts above (5x / 8x) are the
  regression evidence; kept as ordinary single-run tests going forward
  (repeating 5-8x on every CI run would be wasteful) but documented here
  so the next person who sees a flake in this area checks the pooling
  model before assuming it's a new pipeline bug.
- **Neighboring attack:** the *actual* SQLite-lock-contention path
  (`pipeline.py`'s `max_retries = 3` retry loop, catching
  `OperationalError`/`InvalidRequestError`/`DatabaseError`) was never
  exercised meaningfully while these tests ran against a corrupted shared
  connection, since `InterfaceError` is a DB-API sibling of
  `DatabaseError`, not a subclass — the pipeline's retry loop would
  **not** have caught it even if the worker's exception had propagated to
  the main thread. Worth deliberately exercising genuine SQLite
  lock-timeout retry behavior (not connection corruption) as a follow-up
  Phase 10 attack: hold a write lock deliberately and confirm the retry
  loop's 3-attempt bound actually recovers.

### DEPS-01 — `requirements.txt` listed dependencies for the abandoned architecture, and separately was MISSING real ones
- **Severity:** Low (hygiene/bloat side) / **Medium** (the missing-deps
  side — a fresh `pip install -r requirements.txt` would not have
  produced a working install)
- **Area:** Phase 17 — dead code / dependency hygiene
- **Status:** FIXED (session 2, 2026-09-21)
- **Description, unused-dependency side:** `backend/requirements.txt`
  listed `psycopg[binary]`, `celery`, `redis`, and `pgvector`. Confirmed
  by grep that nothing on the actual running application's code path
  imports `psycopg` at all; `celery`/`redis` are only imported by
  `backend/app/worker/celery_app.py`, which nothing else in the codebase
  or test suite imports (fully dead code, see `docs/ARCHITECTURE.md` §6);
  `pgvector`'s two usages (`app/models/event.py`, `app/core/clustering.py`)
  are behind `except ImportError` fallbacks that a deliberate SQLite
  check (`if settings.get_database_url().startswith("sqlite"): raise
  ImportError(...)`) short-circuits **regardless of whether the package
  is installed** — meaning the fallback path is already the only path
  exercised in this product's actual configuration today, independent of
  this finding.
- **Description, missing-dependency side (found while fixing the
  above):** `apscheduler`, `feedparser`, and `tenacity` — all genuinely
  imported by real application code (`app/core/scheduler.py`,
  `app/core/parser.py`, `app/core/providers/llm.py`/`fetcher.py`
  respectively) — were **absent from `requirements.txt` entirely**. A
  clean `pip install -r requirements.txt` followed by `python -m
  app.main` would have failed with `ModuleNotFoundError` the moment the
  scheduler or a feed parse ran. This had gone unnoticed because the
  working `venv_312` had these installed some other way (not tracked to
  a specific origin), masking the gap.
- **Verification, not just inspection:** uninstalled `psycopg`,
  `psycopg-binary`, `celery`, `redis`, `pgvector` from the working venv
  and re-ran the full deterministic suite — **350 passed, 0 failed, no
  change** — and confirmed `from app.main import app` still imports
  cleanly. Then, to prove the *other* direction (completeness, not just
  minimality), built a genuinely separate fresh venv, installed **only**
  from the corrected `requirements.txt`, and re-ran the full deterministic
  suite against it — **350 passed, 0 failed** — proving the trimmed file
  is both minimal and complete, not just inspected-and-assumed.
- **Fix:** `backend/requirements.txt` now lists exactly what's actually
  imported (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `apscheduler`,
  `feedparser`, `tenacity`, `pydantic`, `pydantic-settings`, `httpx`,
  `python-dotenv`, `openai`, `pytest`, `pytest-timeout`), with a comment
  block explaining exactly why `psycopg`/`celery`/`redis`/`pgvector` are
  deliberately absent and what to do if a real Postgres/Celery migration
  is ever undertaken (re-add them deliberately then, not as inherited
  scaffolding).
- **Neighboring attack:** worth periodically re-running the
  fresh-venv-from-requirements.txt check as a lightweight CI step, since
  this exact class of drift (a dependency silently available in a
  long-lived dev venv but absent from the manifest) can reappear anytime
  someone `pip install`s something ad hoc without updating the file.

### SECRET-EXPOSURE-01 — Live API key value printed to tool output (process incident, not a code defect)
- **Severity:** N/A (operator error, not a product vulnerability) — logged
  here for traceability since it involves a real credential
- **Status:** Disclosed to the user in-session; no code change applicable
- **Description:** Early in this session, a presence-check for
  `NVIDIA_API_KEY` was written as `env | grep -i nvidia`, which printed the
  full key value into tool output rather than only confirming it was set.
  Flagged to the user immediately when it happened. No file, log, or
  commit in this repository contains the key — it was only ever visible in
  this conversation's tool-call transcript.
- **Mitigation going forward:** presence/length checks only, never
  printing environment variable values that may hold credentials.
  Confirmed in session 2: `NVIDIA_API_KEY` checked via
  `[ -n "$NVIDIA_API_KEY" ]` (presence + length only, value never
  printed).
- **Rotation:** the key exposed in session 1 has not been rotated by this
  session (that's a user action against the NVIDIA account, out of scope
  for repository changes) — documenting that rotation is recommended if
  that exposure is a concern, without blocking engineering work on it.
- **Code-level defense added (goes beyond this specific incident):**
  `backend/app/core/logger.py::RedactSecretsFilter`, a `logging.Filter`
  that strips NVIDIA/OpenAI/Anthropic API-key shapes,
  `Authorization`/`Bearer`/`Cookie` headers, and generic
  `api_key=`/`token=`/`secret=`/`password=` patterns from every log
  record before it reaches a handler, catching both f-string and
  `%s`-style argument interpolation. Wired into `backend/app/main.py`
  (previously called raw `logging.basicConfig`, bypassing this module
  entirely — `app/core/logger.py` was dead code before this fix, nothing
  imported it). 8 regression tests in
  `backend/tests/test_log_redaction.py`, including one that constructs a
  real `NVIDIAProvider` with a fake-shaped key and confirms it never
  reaches captured log output. `FIXED`.
- **Note:** this specific incident was an operator shell command
  (`env | grep -i nvidia`), not a logging call in the codebase — the
  filter defends against a different, related failure mode (a future
  code change accidentally logging a credential), not the exact incident
  itself. That distinction matters: the filter is a real improvement, not
  a fix for the actual thing that happened.

---

## Not yet attacked (explicitly, so absence isn't mistaken for a clean bill)

Prompt injection beyond the three existing live-NVIDIA test cases;
new SSRF payloads beyond the existing `test_ssrf_attacks_new.py` /
`test_ssrf_redirects.py` suites; XSS against title/summary/entity/evidence/
source-name/URL/image-URL fields; event-relationship red-teaming (model
release vs. deployment-using-that-model, benchmark vs. release, etc.)
beyond what `test_event_relationship_eval.py` /
`test_nvidia_relationship_eval.py` already cover; entity/candidate-explosion
attacks; provenance spoofing beyond `test_origin_attacks.py`; evidence
fabrication beyond `test_evidence_adversarial.py`; importance-score gaming
beyond `test_importance_adversarial.py`; temporal manipulation beyond
`test_temporal_adversarial.py`; concurrency stress beyond the existing
`test_concurrency_race.py` / `test_concurrency_stress.py`; frontend
malformed-API-response testing in a live browser; performance/N+1 query
audit.

All of the above already have *some* existing test coverage (see file
names) — this section is not claiming zero prior work, it's stating that
this session did not add new adversarial cases beyond what was inherited,
and did not independently re-verify the existing adversarial tests'
assertions are still meaningful (as opposed to merely passing).

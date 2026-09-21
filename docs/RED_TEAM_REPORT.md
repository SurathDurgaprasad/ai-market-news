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
- **Status:** OPEN FINDING
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
- **Root cause:** Not yet confirmed. Killed via `Stop-Process` rather than
  let it resolve on its own, so the eventual outcome (timeout exception
  vs. true infinite hang) is unknown. Candidates to rule out next session:
  (a) the configured `timeout=90.0` not actually applying to the phase of
  the request that stalled (e.g. it covers connect+read as one bucket and
  something is resetting the clock via chunked keep-alive), (b) an
  environment-specific network condition unique to this sandbox that
  wouldn't reproduce on a normal developer machine, (c) a genuine upstream
  NVIDIA-side stall independent of this codebase.
- **Fix:** Not yet applied. Two independent actions planned: (1) add
  `pytest-timeout` (or equivalent) so any single test is force-failed
  after a ceiling, converting a silent indefinite hang into a loud,
  diagnosable failure — this is worth doing regardless of the root cause;
  (2) once reproduced outside pytest with full control over signal
  handling, determine whether `NVIDIAProvider` needs explicit
  connect-timeout / read-timeout separation instead of a single float.
- **Regression test:** Not yet written (blocked on root-causing first —
  writing a regression test for an unconfirmed hang mechanism risks
  testing the wrong thing).
- **Neighboring attack:** Once understood, check whether the same stall
  condition is reachable from the *production* ingestion path
  (`IntelligencePipeline` → `NVIDIAProvider`), not just this test, since a
  stalled classify_event call during a real scheduler tick would block
  that tick's entire source-processing loop (it is not currently run with
  any outer wall-clock budget in `scheduler.py::run_ingestion_cycle`).

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
- **Status:** OPEN FINDING
- **Description:** `docs/ARCHITECTURE.md` and root `docker-compose.yml`
  describe PostgreSQL + pgvector + Redis + Celery + OIDC/SAML auth. The
  real, intentional system (confirmed by reading `backend/app/core/config.py`,
  which hardcodes SQLite and explicitly comments *"Do not point this at
  PostgreSQL"*) is FastAPI + SQLite + APScheduler with no auth layer.
  `docs/IMPLEMENTATION_STATUS.md` is similarly stale, describing core
  pipeline logic as "scaffolded"/"not started" when direct code reading
  shows working, tested implementations.
- **Fix:** Not yet applied. Planned for Phase 20: rewrite `ARCHITECTURE.md`
  from the real code, not the other way around; retire or rewrite
  `docker-compose.yml`; retire `IMPLEMENTATION_STATUS.md` in favor of
  `docs/ENGINEERING_STATUS.md` (this session's new file) as the single
  source of truth for current status.

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

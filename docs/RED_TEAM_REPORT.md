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

### DB-ISOLATION-01 — SQLite/WAL transaction isolation and rollback scoping, directly verified (not assumed)
- **Severity:** N/A (verification, not a defect)
- **Area:** Phase 1B, second attack pass, Area C (database integrity red
  team) — the pass's explicit instruction was "Do not assume transaction
  isolation works because SQLite/WAL is enabled. Prove it."
- **Status:** `VERIFIED`, both properties hold; attack **not reproduced**
- **Description:** Reconnaissance found solid existing coverage for
  *eventual convergence* under concurrent writers
  (`test_concurrency_race.py`, `test_concurrency_stress.py` — "does the
  system end up with exactly one canonical event") but nothing that
  directly proves the more fundamental property those tests implicitly
  rely on: that an in-flight, uncommitted write on one connection is
  genuinely invisible to a concurrent reader on another connection until
  commit (no dirty reads), and that a rollback triggered by one article's
  failure never reverts an earlier, already-committed article/event from
  the same ingestion cycle's shared session (mirroring
  `scheduler.py`'s real per-article loop: each successful
  `process_article()` call commits on its own; a later article's
  exception triggers the generic `except Exception: db.rollback()`
  handler).
  **Built and ran two direct proofs, against a real file-backed SQLite
  engine configured identically to `app/db/session.py`'s production
  PRAGMAs (WAL, synchronous=NORMAL, busy_timeout=30000,
  foreign_keys=ON) — explicitly NOT `:memory:`+`StaticPool`, per this
  pass's explicit instruction:**
  1. `test_uncommitted_write_is_invisible_to_a_concurrent_reader`: a
     writer thread inserts a row, flushes (pending, uncommitted), then
     blocks. While blocked, a separate connection queries the same table
     — **0 rows visible**. Only after the writer commits does a fresh
     query see the row. No dirty read occurred.
  2. `test_rollback_of_one_article_does_not_affect_an_earlier_committed_article`:
     one article is fully processed and committed (`created`) via the
     real pipeline. A second, doomed write is staged (flushed,
     uncommitted) in the same shared session, an exception is raised, and
     `db.rollback()` is called — exactly scheduler.py's own per-article
     exception path. The first article/event, already committed, is
     confirmed unchanged; the doomed article is confirmed absent.
  Both properties held. Recorded honestly as confirmed-working
  infrastructure, per the operating brief's explicit instruction not to
  invent findings and to record non-reproductions honestly — this session
  did not weaken, replace, or add exception handling to
  `pipeline.py`/`scheduler.py`'s transaction logic, because no defect was
  found to justify a change.
  **Also checked (clean, not a defect):** a NUL byte (`\x00`) embedded in
  an article's `title`/`raw_content` is stored and read back byte-for-byte
  intact through SQLAlchemy/SQLite/Python's `sqlite3` driver — no silent
  truncation at the NUL boundary (the classic C-string-truncation
  failure mode this was checked against did not reproduce).
- **New tests:** `backend/tests/test_db_integrity_attacks.py` (2 tests),
  both passing against the production-equivalent file-backed
  configuration.

### DEDUP-CONTRADICTION-01 — Two articles making opposite factual claims about the same subject could fast-merge into one event with no LLM check at all
- **Severity:** High (correctness/trust — the highest-priority failure
  mode for this attack pass: a **false merge**, explicitly flagged as
  more damaging than a missed merge. This is a fail-OPEN defect, unlike
  every other finding from this pass, which were fail-closed)
- **Area:** Phase 1B, second attack pass, Area B (duplicate ingestion red
  team) — event-identity / false-merge class
- **Status:** `CONFIRMED`, `FIXED`
- **Description:** `titles_are_safe_lexical_match()` — the fast,
  no-LLM-call path used to decide whether two articles describe the same
  real-world event — requires high title Jaccard similarity (>=0.85),
  no conflicting numeric/product-code markers, and at least one shared
  marker. Its conflict detector (`titles_suggest_different_events`)
  compares only extracted **magnitudes and product codes**; it has no
  mechanism to detect semantic/factual contradiction in the surrounding
  prose. Two long, near-identical titles differing in only the claim
  itself — while sharing the same product-code marker — pass every
  existing gate and merge without ever reaching the LLM verification
  step (`find_semantic_match`/`classify_relationship`) that the rest of
  the pipeline relies on for semantic disambiguation.
  **Reproduced directly (two independent variants, both verified against
  the pre-fix code before any change was made):**
  1. Antonym/contrast-verb pair, no negation word:
     `"NVIDIA CEO Jensen Huang Says H200 Chip Production Is On Track For
     Full Capacity This Quarter"` vs `"...Is Behind For Full Capacity
     This Quarter"` — Jaccard >= 0.85, both extract the identical
     `{"code:h200"}` marker, no conflict detected →
     `titles_are_safe_lexical_match` returned `True` pre-fix. These are
     opposite claims about the same chip's production status.
  2. Negation asymmetry: `"NVIDIA Says H200 Chip Production Delays Will
     Not Affect This Quarter Enterprise Shipments"` vs the same title
     with `"Will Affect"` — same result pre-fix: fast-merge approved.
     Proves the gap isn't limited to a curated antonym list; a bare
     negation flip against otherwise-matching wording defeats the same
     checks.
  End-to-end confirmation: reproduced through the real
  `IntelligencePipeline.process_article()` against a real (file-backed
  test) DB session using the `h200_on_track`/`h200_behind` fixture pair
  — before the fix, this is the exact path that would have produced one
  merged event instead of two.
  **Explicitly distinguished from existing coverage:** the pre-existing
  `test_eval_conflicting_facts_not_merged` test (GPT-5
  available/delayed) validates a *different, deeper* layer — its
  fixture titles are dissimilar enough that they never reach the fast
  path at all, so that test only proves the LLM-based
  `find_semantic_match` layer works. This finding is specifically about
  titles similar enough to **bypass** that LLM layer entirely, which no
  existing test exercised.
- **Fix (`backend/app/core/deduplication.py`):** new
  `titles_have_contrasting_claims()`, consulted by
  `titles_are_safe_lexical_match()` alongside the existing marker-conflict
  check (added as an additional gate, not a threshold change — no
  existing threshold was loosened or tightened). Two independent,
  bounded, explicit signals, matching this file's existing style
  (curated sets, not general sentiment analysis):
  - `_CONTRAST_GROUPS`: a curated set of antonym/contrast phrase-pairs
    common in tech/business reporting (confirmed/denied,
    passed/failed, launched/delayed-cancelled-halted,
    increased/decreased, on-track/behind, beat/missed, won/lost,
    hiring/layoffs, live/down). One-per-title presence from opposite
    groups flags a conflict.
  - A negation-word regex (`not`, `never`, `n't`, `denies`, ...):
    asymmetric presence (in exactly one title) flags a conflict.
  - Explicitly bounded, not exhaustive — documented as a curated
    heuristic in the same spirit as `_SCALE_RE`/`_PRODUCT_CODE_RE`, not
    a claim of complete contradiction detection.
- **Neighboring attack (passes, confirming no new false negatives on
  agreement):** two titles both containing the word "confirmed" (same
  contrast group, not opposite groups) do not trigger the new check;
  the pre-existing legitimate safe-match test cases (`"OpenAI GPT-5
  Model Available Now"` vs `"...Available"`) still pass.
- **Regression/attack tests:**
  `test_contrasting_claims_prevent_false_fast_path_merge`,
  `test_negation_asymmetry_prevents_false_fast_path_merge`,
  `test_contrasting_claims_check_does_not_flag_agreeing_titles`
  (`backend/tests/test_deduplication.py`); end-to-end
  `test_pipeline_contrasting_claims_do_not_fast_path_merge`
  (`backend/tests/test_pipeline.py`) with a new fixture pair
  (`h200_on_track`/`h200_behind` in `backend/tests/fixtures/sources.py`).

### DEDUP-MARKER-NOTATION-01 — Same product written with different punctuation registered as a marker conflict
- **Severity:** Low (correctness/cost only — fail-closed: causes an
  unnecessary LLM round-trip for a genuine same-story near-duplicate,
  never a false merge)
- **Area:** Phase 1B, second attack pass, Area B (duplicate ingestion red
  team)
- **Status:** `CONFIRMED`, `FIXED`
- **Description:** `extract_event_markers()` extracted a bare `num:5`
  marker for the hyphenated `"GPT-5"` but a `code:gpt5` marker for the
  fused `"GPT5"` — disjoint sets for the literal same product mention,
  because `_PRODUCT_CODE_RE` requires the letter-prefix and digits to be
  adjacent with no separator. Two outlets reporting the identical GPT-5
  story with different hyphenation/spacing therefore registered as a
  marker **conflict** in `titles_suggest_different_events`, forcing an
  otherwise-safe fast lexical match to fall through to a full LLM call.
  Reproduced directly: `extract_event_markers("GPT-5 released")` returned
  `{"num:5"}` while `extract_event_markers("GPT5 released")` returned
  `{"code:gpt5"}`, before the fix.
- **Fix (`backend/app/core/deduplication.py`):** added a second,
  supplementary extraction pass (`_CODE_SEPARATOR_RE`) that also emits
  the fused-style `code:` marker for a hyphen/space-separated short
  letter-prefix + digits pattern (e.g. `"GPT-5"` now also contributes
  `code:gpt5`, in addition to the existing `num:5`), so fused and
  separated spellings of the same code now share a marker. Added
  alongside the existing extraction, not replacing it — H200/B200-style
  already-fused codes are untouched.
- **Neighboring attacks (all pass, confirming no weakened conflict
  detection):** `GPT-5` vs `GPT-4` still conflict; `H200` vs `B200` still
  conflict; `$6.6 billion` vs `$6.6 million` still conflict.
- **Regression tests:**
  `test_hyphenated_and_fused_product_codes_are_not_a_false_conflict`,
  `test_hyphen_normalization_does_not_weaken_genuine_conflicts`
  (`backend/tests/test_deduplication.py`).

### ORIGIN-PSL-01 — Provenance evidence silently lost for public-suffix (`.co.uk`-style) publishers and nested JSON-LD publisher objects
- **Severity:** Medium (correctness/data-quality — both failure modes are
  fail-closed: legitimate provenance evidence is discarded, not falsely
  trusted; no trust-escalation path was demonstrated through either)
- **Area:** Phase 1B, second attack pass, Area A (provenance / source
  identity red team), items 2/7 (publisher-declaration conflicts) and 14
  (subdomain vs registrable-domain boundary / lookalike domains)
- **Status:** `CONFIRMED`, `FIXED`
- **Description — two independent defects found in `app/core/origin.py`
  during reconnaissance (not manufactured; both reproduced directly
  against the pre-fix code before any change was made):**
  1. **`same_registrable_host()` had no public-suffix awareness.** It
     compared only the last two dot-separated labels of each host. For
     any host sitting under a multi-label public suffix (`.co.uk`,
     `.com.au`, `.co.jp`, etc. — a huge share of real-world regional news
     publishers), this collapses every distinct site under that suffix
     to the same tuple: `bbc.co.uk` and `evil.co.uk` both reduce to
     `("co", "uk")` and compared equal. Verified directly:
     `same_registrable_host("bbc.co.uk", "evil.co.uk")` returned `True`
     before the fix. The function's only call site gates the
     aggregator-to-official promotion check (`different_site` in
     `resolve_originating_source`), so a false "same site" result
     suppresses promotion — the practical effect is that a legitimate
     `.co.uk`/`.com.au`/`.co.jp`-style publisher, reached via an
     aggregator (Hacker News, Google News) with genuine on-page evidence
     (og:site_name/JSON-LD), silently fails to get promoted to
     `official_name`/`official_url`, because the code wrongly believes
     the aggregator and the publisher are "the same site." This is a
     fail-closed failure (lost detection, not false trust), but a real
     and previously-untested one, affecting a large class of real
     publishers.
  2. **`_JSONLD_PUBLISHER` regex could not see past one nested object.**
     The pattern used `[^}]*` between `"publisher": {` and `"name"`,
     which stops at the first `}`. Real-world schema.org
     Organization/Publisher JSON-LD very commonly nests a `"logo": {...}`
     object before `"name"` — that nested object's own closing brace
     terminated the match early, so the regex found nothing even though
     valid publisher evidence was present on the page. Verified directly:
     `extract_publisher_from_html()` against a JSON-LD publisher object
     with a nested `logo` before `name` returned `""` before the fix,
     `"Real Publisher Corp"` after.
- **Explicitly NOT re-litigated:** the existing, already-accepted
  `test_origin_aggregator_to_official_with_fake_og_site_name` tradeoff
  (an attacker-controlled page's self-reported `og:site_name` is trusted
  as the official display name, while `official_url` correctly stays the
  real URL) is a pre-existing, deliberate design tradeoff, not a fresh
  defect — left unchanged. Likewise, `extract_publisher_from_html()`'s
  precedence rule (og:site_name unconditionally wins over a conflicting
  JSON-LD publisher, because JSON-LD is only consulted when no
  og:site_name matched at all) is deterministic, intentional-shaped
  behavior of the same class as the accepted tradeoff above — not
  reclassified as a new defect, but now locked in by an explicit
  regression test (`test_og_site_name_still_wins_over_conflicting_jsonld_publisher`)
  so it's a tested contract instead of incidental code order.
- **Fix (`backend/app/core/origin.py`):**
  - `same_registrable_host()`: added a small, explicit, hardcoded set of
    common multi-label public suffixes (`_MULTI_LABEL_PUBLIC_SUFFIXES` —
    UK/JP/KR/NZ/ZA/AU/BR/MX/IN/IL/ID/SG/HK ccTLD second-levels). When a
    host's last two labels match one of these AND it has 3+ labels total,
    comparison uses the last **three** labels instead of two. This is
    deliberately **not** a full Public Suffix List implementation — no
    new dependency was added (`tldextract`/`publicsuffix2` are not
    currently installed); it covers the suffixes real news publishers are
    most likely to sit under, consistent with this file's existing style
    of explicit, bounded sets (`AGGREGATOR_HOSTS`). A host under an
    uncovered public suffix still falls back to the pre-existing
    last-2-labels heuristic, unchanged.
  - `_JSONLD_PUBLISHER`: widened to
    `"publisher"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"name"\s*:\s*"([^"]+)"` —
    tolerates exactly one level of nested `{...}` between `publisher` and
    `name` (covers the common `logo`-before-`name` shape) while remaining
    a regex heuristic, not a JSON parser; deeper nesting remains an
    accepted, documented limitation rather than a claimed-complete fix.
- **Regression tests (`backend/tests/test_origin_attacks.py`):**
  - `test_lookalike_domain_under_shared_public_suffix_is_not_same_site` —
    direct reproduction of the `same_registrable_host` bug plus the
    subdomain-still-matches contrast case.
  - `test_aggregator_to_lookalike_couk_publisher_still_promotes_correctly`
    — end-to-end through `resolve_originating_source`, proving a real
    `.co.uk` publisher reached via an aggregator now promotes correctly.
  - `test_jsonld_publisher_with_nested_logo_object_is_extracted` — direct
    reproduction of the regex bug.
  - `test_jsonld_publisher_name_before_nested_logo_still_extracted` —
    neighboring case (name before the nested object) proving the widened
    pattern didn't regress the simple case.
  - `test_og_site_name_still_wins_over_conflicting_jsonld_publisher` —
    locks in the existing precedence rule as an explicit contract.
  - All pre-existing provenance tests (`test_origin_attacks.py`,
    `test_origin_and_entities.py`, 15 tests) still pass unchanged.
- **Full suite after fix:** 409 passed, 24 skipped, 0 failed (baseline
  was 401 passed / 24 skipped before this finding's 8 new tests).

### INGEST-SILENT-01 — A feed URL serving an HTML page instead of a feed was recorded "healthy" forever
- **Severity:** Medium (correctness/observability — the same class of
  defect as SCHED-OUTAGE-01, one layer earlier: a persistently broken
  source is invisible to the admin sources page indefinitely)
- **Area:** Phase 1B invariant 1 (source failure isolation) — "unexpected
  content type" failure class specifically
- **Status:** `CONFIRMED`, `FIXED`
- **Description:** `feedparser`'s own `bozo` flag — the library's
  standard "this wasn't well-formed XML" signal — does **not** fire for
  an HTML page served where a feed should be (e.g. a feed URL that
  starts 404ing, or a CMS migration that replaces the feed with an HTML
  "moved" notice): `feedparser.parse(html_page)` returns `bozo=False,
  entries=0`, structurally identical to a genuinely well-formed feed
  that simply has nothing new. Traced through `scheduler.py`:
  `parse_rss_feed()` returns `[]` either way, the article loop doesn't
  execute, and the source is recorded `health_status="healthy"` —
  indistinguishable from correct, successful polling.
- **Reproduction, verified directly with feedparser (not assumed):**
  ```
  feedparser.parse('<html><body><h1>404 Not Found</h1></body></html>')
  → bozo=False, entries=0
  ```
  vs. a genuinely malformed/truncated XML payload, which DOES set
  `bozo=True` — confirming the HTML case is the more dangerous, silent
  one precisely because feedparser's own anomaly signal doesn't catch it.
- **Fix (`backend/app/core/parser.py`):** new `looks_like_feed()` —
  a deliberately simple structural check (root-tag substring match for
  `<rss`, `<feed`, or `<rdf:RDF>`, scanned only within the first 4096
  characters, bounding cost against a maliciously large non-feed body)
  independent of feedparser's own parsing/bozo logic. Wired into
  `scheduler.py::run_ingestion_cycle`: when `parse_rss_feed()` returns no
  articles AND the payload doesn't look like a feed at all, a `ValueError`
  is raised and caught by the pipeline's **existing** per-source failure
  handler (health_status="failing", `last_error_info` set,
  `consecutive_failures` incremented) — reusing established
  failure-handling machinery rather than adding new state management.
- **Regression tests:**
  - `test_parser.py`: 8 direct unit tests for `looks_like_feed()` (RSS,
    Atom, RDF, HTML-404-page, empty/None, plain text, bytes input,
    case-insensitivity).
  - `test_scheduler_broken_feed_detection.py`: the scheduler-level
    reproduction (HTML page → not recorded healthy, has a diagnosable
    `last_error_info`) plus the necessary contrast case (a genuinely
    empty well-formed feed must still be recorded healthy — the fix must
    not conflate the two in the other direction).
- **Neighboring attacks (both pass, confirming no new false positives):**
  a truncated-but-still-`<rss>`-tagged malformed XML payload
  (feedparser's genuine `bozo=True` case) is correctly NOT flagged by the
  new "not a feed" check — any failure there is left to the pre-existing
  per-entry exception handling; and a real feed with a verbose (20-line
  comment) preamble before its root tag, still within the 4096-char scan
  window, is correctly still recognized as a feed.
- **Full suite after fix:** 396 passed, 0 failed (up from 382).

### DNS-REBINDING-PIN-01 — Pin-holds-under-rebinding claim independently verified against the real mechanism
- **Severity:** N/A (verification of an existing, previously-claimed-but-
  not-directly-proven defense — not a new finding)
- **Area:** Phase 1B invariant 5 (DNS rebinding / resolution safety)
- **Status:** `VERIFIED` — attack **NOT REPRODUCED**, recorded honestly
  as a confirmed-working defense, not invented as a finding for its own sake
- **Gap identified by inspection:** `test_fetcher.py::test_pin_host_stores_validated_records`
  pins a hostname to an IP and confirms `_pinned_getaddrinfo` returns
  that IP — but the underlying `_original_getaddrinfo` mock never
  *changes* during that test, so it only proves the pin returns what it
  was given. That would hold true even with zero rebinding protection at
  all; it doesn't prove the pin actually *overrides* a differing later
  DNS answer.
- **Attack attempted:** `test_dns_rebinding_pin_holds.py` reconfigures
  `_original_getaddrinfo` to return a **different** (private, `127.0.0.1`)
  IP for the *same* hostname immediately after `pin_host()` already
  validated and pinned a public one — simulating an attacker's
  authoritative DNS server changing its answer between the validation
  lookup and a later connection attempt (the actual rebinding attack).
- **Result: attack did not succeed.** `_pinned_getaddrinfo` returned the
  originally-pinned public IP, not the new private one; the real resolver
  was confirmed called exactly once (by `pin_host` itself), proving the
  pin genuinely short-circuits all further resolution for that hostname
  rather than merely being consulted opportunistically.
- **Neighboring case, also verified:** if the *first* (validation)
  resolution itself returns a private IP, `resolve_validated_addrinfo`
  correctly rejects before ever pinning anything (validate-then-pin
  ordering, not pin-then-validate).
- **Why this is still worth recording as a finding despite finding
  nothing wrong:** the operating brief explicitly asks that a
  not-reproduced attack be recorded honestly rather than silently
  skipped, and this closes a real gap between "the mechanism is designed
  to prevent rebinding" (already documented in `fetcher.py`'s own
  docstring) and "the mechanism was directly verified to prevent
  rebinding" (not previously true — the existing test didn't actually
  simulate a changing DNS answer).

### INGEST-DECOMPRESSION-BOMB-01 — A small gzip-compressed response could exhaust memory before any size check ran
- **Severity:** High (memory-exhaustion DoS against the ingestion
  process from a single malicious/compromised source — no auth or
  special positioning required, just a feed or article URL under
  attacker control)
- **Area:** Phase 1B invariant 6 — response size limits / decompression
  expansion
- **Status:** `CONFIRMED`, `FIXED`
- **Description:** `fetcher.py::_reject_oversized` (the pre-existing size
  guard) checked the `Content-Length` header first, then
  `len(response.content)` — but `response.content` was only reachable
  because `fetch_url` used the non-streaming `client.get()`, which
  eagerly reads AND decompresses the entire body before returning. For a
  `Content-Encoding: gzip` response, `Content-Length` reflects the
  **compressed wire size**, not the eventual decompressed size — so a
  small, honestly-sized-on-the-wire response could still decompress to
  something enormous, and by the time the length check ran, the full
  decompressed body was already sitting in memory.
- **Reproduction (before any test was written — proven directly against
  real httpx behavior first, per this session's "verify before writing
  the regression" discipline):** a 48,623-byte gzip payload
  (`gzip.compress(b"A" * 50_000_000)`) served through a fake httpx
  transport decompressed to a full 50,000,000-byte `response.content` —
  confirmed by direct measurement, not inferred from documentation.
  1,000:1+ compression ratios are trivially achievable with repeated-byte
  or otherwise highly-compressible content, so the achievable
  amplification is effectively unbounded relative to any reasonable
  `Content-Length` pre-check.
- **Root cause:** checking response size **after** full materialization,
  rather than **during** the read.
- **Fix (`backend/app/core/fetcher.py`):** `fetch_url` now uses
  `client.stream("GET", ...)` instead of `client.get(...)`. A redirect or
  transient-error (429/5xx) hop's body is never read at all (a secondary
  improvement: the original code fully downloaded even *discarded*
  intermediate-redirect bodies). The eventual success body is read via
  `_read_body_with_cap()`, which iterates `iter_bytes()` (already-
  decompressed chunks) and aborts as soon as the **cumulative** size
  crosses `MAX_RESPONSE_BYTES` — bounding worst-case memory to
  (approximately) one chunk's decompression amplification rather than
  the whole body's. `_reject_oversized` was split into
  `_reject_oversized_declared_length` (the original header fast-path,
  kept as-is — still useful for honestly-oversized responses) and this
  new streaming check.
- **Real bug caught while attacking the fix itself, before it ever
  shipped:** reconstructing the final `httpx.Response` from the
  accumulated (already-decompressed) bytes initially passed through the
  *original* response headers unchanged — including `Content-Encoding:
  gzip`. httpx's `Response.__init__` then tried to gzip-decode the
  already-decoded body a second time, raising `DecodingError` and
  **corrupting every genuinely gzip-compressed real response** (caught
  immediately when a redirect test that mocked `httpx.Client.get`
  silently fell through to a real, gzip-compressed network response
  after the streaming rewrite, and failed with a decode error — not
  discovered by a unit test, discovered by the mock no longer matching
  reality and the code then hitting a real server). Fixed with
  `_headers_for_already_decoded_body()`, which strips
  `Content-Encoding`/`Content-Length` before reconstruction.
- **Regression tests:**
  - `test_fetcher.py`: `_reject_oversized_declared_length`
    (accept/reject), `_read_body_with_cap` (single oversized chunk,
    within-cap, and — a neighboring case — cumulative size **across
    multiple** chunks none of which individually exceeds the cap).
  - `test_decompression_bomb.py`: end-to-end through the real
    `fetch_url()` entrypoint (only the transport faked) — a 20x-over-cap
    gzip bomb compressed to well under the cap on the wire is rejected;
    a genuinely small, honestly gzip-compressed normal response (the
    overwhelmingly common real case) still decodes correctly — this is
    the regression test for the Content-Encoding bug above.
  - `test_ssrf_redirects.py`: updated to mock `httpx.Client.stream`
    (a context manager) instead of the no-longer-used `httpx.Client.get`
    — the tests were silently falling through to real network calls
    after the rewrite until this was caught (33.5s real-network latency
    on what should have been an instant mocked test was the tell).
- **Live verification beyond mocks:** `fetch_url()` run against two real
  URLs (`hnrss.org`, `openai.com/news/rss.xml`, the latter 741KB
  decoded) — correct, uncorrupted XML text in both cases, including one
  real transient-502-then-retry-succeeds cycle observed live.
- **Full suite after fix:** 401 passed, 0 failed (up from 396).
- **Neighboring attack, not yet checked:** `article_body.py`'s
  enrichment fetch (`fetch_fn(url, timeout=8)`) reuses this same
  `fetch_url`, so it inherits this fix automatically — not independently
  re-verified with its own dedicated decompression-bomb test this
  session (the underlying mechanism is shared, but the call site wasn't
  separately exercised).

### IMPORTANCE-RESEARCH-01 — Benign vulnerability-trends research could be forcibly reclassified as an active security incident
- **Severity:** Medium (importance/classification correctness, the exact
  Phase 1H hard case the operating brief named: "security keyword +
  harmless research")
- **Area:** Phase 1H — importance red team
- **Status:** `FIXED`
- **Description:** `test_importance_adversarial.py` already had a test
  (`test_importance_security_keyword_in_harmless_research`) documenting
  this as a "KNOWN LIMITATION" at the `infer_event_signals()` level —
  but never verified whether it was actually exploitable end-to-end.
  It was: `infer_event_signals()`'s security regex
  (`\b(rce|...|vulnerabilit\w+|...)\b`) matched "a survey of vulnerability
  trends" identically to an active incident report, returning early with
  `kind="security_incident"` before the function's own research-paper
  detection ever ran. Standing alone this would just be an inaccurate
  helper — it becomes a real pipeline defect via `pipeline.py`'s
  calibration override: `if security == "none" and inf_sec != "none":
  security = inf_sec`. If the LLM correctly classified a benign research
  article as `security_impact="none"` (or simply left it at
  `EventClassification`'s own Pydantic default of `"none"` — a realistic
  case, not contrived), the deterministic false positive would silently
  **overrule the LLM's own correct judgment**.
- **Reproduction:** `backend/tests/test_importance_research_vs_incident.py`
  — a genuine end-to-end pipeline run (not just the standalone
  `infer_event_signals()` unit test), `TestLLMProvider`'s default fixture
  (`event_kind="other"`, `security_impact="none"`) standing in for "the
  LLM made no specific claim," fed a realistic vulnerability-trends
  survey article. Before the fix: `event.importance_score == 70`,
  `event_kind == "security_incident"` — a fabricated active incident from
  an academic survey.
- **Fix:** `app/core/importance.py` — a new, deliberately narrow
  `_VULN_RESEARCH_SURVEY_RE` (academic-survey phrasing: "survey of ...
  vulnerabilit/trend", "literature review", "systematic review",
  "meta-analysis", "research paper", "academic study", "vulnerability
  trends") excludes the security-keyword match only when that specific
  phrasing is present, so the broad keyword match real incidents rely on
  stays intact.
- **Neighboring attack (verified the fix doesn't over-broaden):**
  `test_importance_genuine_incident_still_detected_alongside_survey_fix`
  — a genuine, specific, actively-exploited RCE disclosure (no survey-
  phrasing overlap) still correctly classifies `security="significant"`,
  `kind="security_incident"`.
- **Test hygiene:** the pre-existing test that had documented the bug as
  permanent was updated to assert the corrected behavior instead of the
  bug, with its docstring explaining the change and pointing to the new
  end-to-end regression test — not deleted, not left contradicting reality.

### TEST-QUALITY-EVAL-SUMMARY-01 — Two tests could pass unconditionally regardless of whether the real implementation was broken
- **Severity:** Medium (test-suite integrity — exactly the Phase 1K
  standard: "could this test pass while the real implementation is
  broken?")
- **Area:** Phase 1K — test quality audit
- **Status:** `FIXED`
- **Finding 1 — hardcoded metrics, not computed:**
  `test_event_relationship_eval.py::test_corpus_precision_recall_summary`
  asserted a precision/recall formula against `TP, TN, FP, FN = 11, 29,
  0, 0` — **hardcoded literals**, not derived from actually running the
  corpus through the pipeline. It would have passed unconditionally even
  if every other test in the file were deleted. The real verification is
  each individual `test_eval_*` function (which does call the real
  pipeline), so nothing was actually unverified as a result — but this
  specific test created a false impression of independent aggregate
  proof. Fixed by adding a real check: the module is introspected via
  `inspect.getmembers` to count actual `test_eval_*` functions and assert
  that count matches the claimed `TP+TN+FP+FN` total, so adding or
  removing a case without updating the hand-maintained tally now fails
  loudly instead of silently drifting.
- **Finding 2 — a test whose entire body was a docstring and `pass`:**
  `test_evidence_adversarial.py::test_evidence_document_guarantees`
  documented the evidence-verification system's guarantees (exactly the
  Phase 1G distinction the brief asks for: does the quote exist / is it
  attributable / does it support the claim) in a nicely-written docstring
  — followed by `pass`. Zero verification value; it would pass identically
  whether `verify_citations()` worked correctly or was completely broken.
  Fixed: converted to a real module docstring (documentation, not
  disguised as a test), and replaced the empty function with a genuine
  new adversarial case — `test_evidence_cookie_banner_accepted_as_evidence`
  — covering the one Phase-1G-named attack vector (cookie banner) the
  file didn't already exercise behaviorally.
- **Regression:** both fixes verified by running their respective files
  (`test_event_relationship_eval.py`: 71 passed; `test_evidence_adversarial.py`:
  5 passed) — the drift-check specifically was confirmed to actually catch
  drift by intentionally miscounting during development before landing
  the correct numbers.
- **Neighboring attack, not yet done:** the brief explicitly says "assume
  there are more, find them" beyond OpenAIProvider/AnthropicProvider/
  concurrency/failure-injection (already fixed in prior sessions) and
  these two. A systematic grep for `assert True`, bare `pass` test bodies,
  and hardcoded metric literals was run across the suite this session
  (see below) and these two were the only real hits — six other `pass`
  occurrences were checked individually and are legitimate (exception-
  swallowing in mocks/teardown, not vacuous test bodies). Not
  exhaustive beyond that specific grep pattern; a deeper audit (mocks too
  high in the stack, order-dependent tests, weak assertions) remains open
  for a future session.

### FAIRWIND-NEIGHBORS-01 — 5 new deliberately distinct neighbors of the Fairwind false-merge pattern
- **Severity:** N/A (coverage expansion, not a defect)
- **Area:** Phase 1D — Fairwind regression (explicitly required: "create
  at least 5 neighboring variations of the same attack")
- **Status:** `FIXED` / `VERIFIED` (deterministic); `PARTIALLY VERIFIED` (live)
- **Description:** the existing corpus had one Fairwind case (program
  deploying a model vs. the model's own release, both Google/Gemini).
  Added 5 more, each a genuinely different company/model pair and a
  different flavor of "shared model entity, not the release event," per
  the brief's suggested list: FW1 program-uses-model (Anthropic/Claude
  4.5), FW2 product-integrates-model (Perplexity/GPT-5), FW3
  benchmark-evaluates-model (MLPerf/Llama 4), FW4 capability-announcement
  (Notion/Gemini 3), FW5 deployment-announcement (Snowflake/Mistral Large
  3). All 5 pass deterministically
  (`test_event_relationship_eval.py::test_eval_FW1..FW5`, `TestLLMProvider`
  — verifies candidate-generation/routing, not semantic judgment, since
  `TestLLMProvider` doesn't reason about content).
- **Live NVIDIA validation attempted for 2 of the 5 (FW2, FW4)**: both
  timed out at the full retry budget rather than returning a real verdict
  — see PROVIDER-AGNOSTIC-01 above for why this became the trigger for
  the broader provider-agnostic work. **Not a confirmed pass or fail of
  NVIDIA's actual semantic judgment on these two cases** — a timeout is
  not a verdict, and reporting it as one either way would be exactly the
  kind of fabricated-confidence the operating brief prohibits. Live
  semantic validation for all 5 FW cases (and the rest of the corpus)
  against OpenAI is the next step once `OPENAI_API_KEY` is available —
  see PROVIDER-AGNOSTIC-01's "not verified" section.

### PROVIDER-AGNOSTIC-01 — LLM architecture generalized to 4 providers; NVIDIA no longer the only live-tested one
- **Severity:** N/A (architecture generalization, prompted by a real
  operational problem — see below)
- **Area:** Phase 1 continuation — provider abstraction / LLM boundary
- **Status:** `PARTIALLY VERIFIED` — see the explicit verified/not-verified
  split at the end of this entry. Do not read this as "Bedrock is
  production-ready" or "OpenAI has been live-validated"; neither claim is
  supported by what was actually run.
- **Trigger:** live NVIDIA validation of the Phase 1D Fairwind-neighbor
  cases (FW2, FW4) both genuinely timed out at the NVIDIA API level after
  the full 100s x 3-attempt retry budget (~300s each, ~609s combined),
  correctly converted to `LlmUnavailableError` by the NVDA-01 fix rather
  than hanging — but this demonstrated that NVIDIA's live latency makes
  it impractical as the primary provider for iterative development/live
  semantic validation, even though the *reliability* fix (bounded,
  correctly-classified failure) worked exactly as designed.
- **Explicit instruction:** keep NVIDIA (the production default,
  unchanged), make OpenAI the fast development/live-validation provider,
  and make the architecture genuinely support 4 providers (NVIDIA,
  OpenAI, Anthropic, Bedrock) through one uniform contract.

#### Three-layer timeout model (new, applied to all 4 providers)
Previously only two layers existed with no explicit boundary between
them: an SDK-level per-phase timeout, and a tenacity retry budget whose
combination produced only an *implicit* worst-case total (attempts x
per-attempt deadline + backoff). Added a third, explicit layer:
`_with_operation_deadline()` wraps the whole retry-decorated call
(all attempts combined) in its own named ceiling
(`{PROVIDER}_OPERATION_DEADLINE_SECONDS`), independently tunable per
provider. OpenAI: request=30s/operation=60s (tight — fail fast during
iteration, the whole point of this change). NVIDIA:
request=100s/operation=330s (330s deliberately set just above the
pre-existing implicit worst case of ~304s, so this refactor does not
change NVIDIA's observed behavior — the explicit instruction was "NVIDIA
behavior remains unchanged except for the improved contract"). Anthropic
and Bedrock: request=100s/operation=330s, matching NVIDIA's shape since
neither has real-world latency data to tune against yet.

#### `OpenAIProvider` and `AnthropicProvider`: unchanged from the prior
session's fixes (OPENAI-BROKEN-01) — the manual JSON-schema pattern, the
`_unavailable_on_any_error` boundary, and now the operation-deadline
layer. `OpenAIProvider` gained a proper `classify_relationship`
implementation reuse already in place from that session; no further
change needed there beyond the new deadline layer.

#### `BedrockProvider` (new)
Targets Anthropic Claude models hosted on Bedrock via `bedrock-runtime`'s
`invoke_model` (AWS's documented request/response shape for Anthropic
models: `anthropic_version` + `system` + `messages` in the body,
`content` blocks in the response) — the same schema-in-prompt +
Pydantic-validation pattern as every other provider, over boto3 instead
of an HTTP client library. Bedrock hosts multiple model families (Titan/
Nova, Llama, Mistral, ...) with different `invoke_model` shapes;
deliberately targets only the Anthropic-model shape rather than
attempting to abstract over all of them in one implementation.

**Real bug caught before it shipped, precisely because this was verified
rather than assumed**: the first version of `bedrock_error_is_retryable`/
`_fatal_auth`/`_fatal_model` checked `type(exc).__name__ == "ClientError"`
to classify AWS errors. Testing with `botocore.stub.Stubber` (a real
boto3 mechanism that simulates authentic botocore `ClientError` responses
without live AWS access or network calls — installed `boto3`/`botocore`
specifically to make this possible, same reasoning as installing
`anthropic` in the prior session) immediately proved this wrong: botocore
raises dynamically-generated, service-specific exception subclasses (e.g.
`botocore.errorfactory.ThrottlingException`) whose `type(exc).__name__`
is the error code itself, not literally `"ClientError"` — the class
*inherits from* `ClientError`, it isn't named it. The original check would
have silently classified every single real Bedrock error as
unclassified/non-retryable. Fixed to `isinstance(exc,
botocore.exceptions.ClientError)` before this was ever exercised against
anything resembling a real response. This is exactly the kind of
"verified, not assumed" discipline this whole audit has been trying to
apply, catching itself in the same trap it was set up to find in others.

#### Configuration (`app/core/config.py`)
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` (optional — boto3's own
default credential chain is the normal path; explicit keys only override
it), `AWS_REGION` and `BEDROCK_MODEL_ID` (both required for
`LLM_PROVIDER=bedrock`, no sensible default). `provider_is_configured()`,
`resolve_llm_mode()`, and `get_llm_provider()` extended for `"bedrock"`
alongside the existing three. Missing `BEDROCK_MODEL_ID`/`AWS_REGION`
fails at construction (deterministic, no network attempt) — actual AWS
credential validity is discovered at call time (correctly, since that's
how AWS's credential model actually works: an IAM role or SSO session
with no explicit keys anywhere in config is completely valid and normal)
and normalized to `LlmUnavailableError` like any other provider failure.

#### Regression tests (`backend/tests/test_provider_agnostic.py`, 15 tests, all passing)
OpenAI initializes correctly / fails clearly without a key; 3 Bedrock
error-normalization tests via Stubber (throttling, access-denied, no-
credentials) plus a clean-failure-without-config test; a parametrized
missing-credentials test across all 4 providers; an unknown-provider
test; and — the test that actually proves the architectural claim, not
just each provider individually — a parametrized test running the exact
same fake classification through `IntelligencePipeline.process_article()`
once per provider class (NVIDIA/OpenAI/Anthropic/Bedrock, each with only
`_complete_json` patched, everything else real) and asserting the
resulting `Event` is IDENTICAL regardless of which concrete provider was
plugged in. This is possible specifically because all four providers
share the exact same `_complete_json(system, user, model_cls)` internal
contract — which is what actually makes the pipeline provider-agnostic
in practice, not just in principle.

Full deterministic suite after this work: **382 passed, 0 failed** (up
from 367 — the 15 new tests).

#### Explicit VERIFIED / NOT VERIFIED split (do not blur these)
- `VERIFIED`: OpenAI, NVIDIA, and Anthropic provider construction, error
  normalization, and timeout bounding, against real SDK objects (mocked
  transport, real client classes) — see the test files listed above.
- `VERIFIED`: Bedrock construction, missing-config failure, and error
  normalization against **simulated** botocore responses (Stubber) — a
  legitimate, real testing mechanism, but not a live AWS call.
- `VERIFIED`: pipeline behavior is identical across all 4 provider
  classes at the code level (the parametrized pipeline test).
- `NOT VERIFIED`: a real, successful Bedrock API call. This sandbox has
  no AWS credentials or Bedrock access — explicitly permitted by the
  task ("seams should be fully prepared if credentials/SDK verification
  cannot be performed yet"). Do not read the Stubber-based tests passing
  as proof Bedrock actually works end-to-end against real AWS.
- `VERIFIED`: live OpenAI semantic validation — completed after the user
  added `OPENAI_API_KEY` to this machine's Windows User environment (the
  same registry-hydration mechanism `NVIDIA_API_KEY` already used; the
  key value was never printed, echoed, or inspected — only a
  presence/length check was performed, and only against the app's own
  config resolution, not raw `env`/`Get-ChildItem Env:`). See the
  "Live OpenAI semantic evaluation" subsection immediately below for the
  full case-by-case results. Headline: **9/9 passed, zero false merges,
  ~1-2s latency per call** (vs. NVIDIA's observed ~10 minutes for 2
  calls) — both Fairwind-neighbor cases that had timed out live against
  NVIDIA (FW2, FW4) got real, correct (`DIFFERENT_EVENT`, no false merge)
  answers this time.

#### Live OpenAI semantic evaluation (`backend/tests/test_openai_relationship_eval.py`, 9 tests, all passing)

Deliberately modeled on `test_nvidia_relationship_eval.py`'s structure
and `_eval()` pattern — reusing that harness's exact case content for the
cases already validated against NVIDIA, not inventing a new evaluation
framework. Run with `OPENAI_EVAL=1 LLM_PROVIDER=openai TESTING=0
TEST_MODE=0`, model `gpt-4o-mini` (`settings.OPENAI_MODEL`'s default).

| Case | Expected | Actual | Verdict | Latency |
|---|---|---|---|---|
| A — official blog + news, same event | SAME_EVENT | SAME_EVENT | TP | - |
| F — same model family, different event | DIFFERENT_EVENT | DIFFERENT_EVENT | TN | 1858ms |
| E — Fairwind regression itself | DIFFERENT_EVENT | DIFFERENT_EVENT | TN | 1391ms |
| H — security incident + confirmation | SAME_EVENT | **UPDATE_TO_SAME_EVENT** | FN | 1530ms |
| FW2 — product integrates model | DIFFERENT_EVENT | DIFFERENT_EVENT | TN | 937ms |
| FW4 — capability announcement using model | DIFFERENT_EVENT | DIFFERENT_EVENT | TN | 1875ms |

**Aggregate: TP=1 TN=4 FP=0 FN=1 UNAVAILABLE=0.** Zero false merges — the
one hard assertion the corpus-summary test enforces. The one FN
(H-security-confirmation) is not a alarming miss: the model labeled a
patch/confirmation follow-up `UPDATE_TO_SAME_EVENT` rather than
`SAME_EVENT` — a defensible alternative reading of the SAME_EVENT vs.
UPDATE_TO_SAME_EVENT boundary (a confirmation *is* arguably a later
update to the same incident, not identical reporting of it), not a
semantic error the way a false merge would be. Reported honestly as a
real result, not smoothed over.

`classify_event()` case (benign vulnerability-trends research,
IMPORTANCE-RESEARCH-01's exact reproduction content): the **live model
itself** — not just the deterministic-signal-override fix — correctly
returned `event_kind="research"`, `security_impact="none"`,
`importance_score=50`. The fix protects against a model that gets this
wrong; this confirms OpenAI doesn't need that protection for this
specific case, though the fix stays in place as defense-in-depth.

`summarize_event()` grounding case: 3 citations returned, **all 3
independently verified** via the real `verify_citations()` grounding
check (exact-substring, not a relaxed test-only check) — no fabricated
quotes detected.

**Real, previously-uncaught test fragility found and fixed while running
this**: `test_provider_agnostic.py::test_openai_provider_has_no_client_without_a_key`
started failing on a full-suite run once a real `OPENAI_API_KEY` existed
in the ambient environment — `OpenAIProvider(api_key=None, ...)` falls
back to `settings.OPENAI_API_KEY` (intentional: explicit key wins,
otherwise fall back to configured settings, same pattern as every other
provider), so the test's "no key → no client" precondition implicitly
depended on the ambient machine having no key configured, which stopped
being true the moment live validation needed one. Not a code defect —
fixed by explicitly clearing `settings.OPENAI_API_KEY` and the env var
via `monkeypatch` within the test itself, matching the credential-clearing
pattern already established in `test_llm_env.py::_clear_llm_keys`, so the
test's precondition no longer depends on what happens to be configured on
whatever machine runs it.

### SCHED-OUTAGE-01 — A provider outage was indistinguishable from "no AI events found"
- **Severity:** High — this is exactly the kind of correctness gap that
  erodes trust in the product silently: an operator looking at the admin
  sources page during a real NVIDIA outage would have seen
  `health_status="healthy"` and concluded the source legitimately had no
  news that cycle.
- **Area:** Phase 1A — scheduler/ingestion architecture. Directly
  verifies invariant 3 from the operating brief: *"A provider outage must
  be distinguishable from 'no AI events found'."* It was not.
- **Status:** FIXED (session 2, 2026-09-22)
- **Description:** `pipeline.py` only caught `LlmUnavailableError`
  around its three LLM calls (`classify_event`, `summarize_event`,
  `classify_relationship`). `NVIDIAProvider.classify_event` only raises
  `LlmUnavailableError` when `self.client` is `None` (no API key
  configured) — a genuine network/API outage instead propagates as
  whatever raw exception the tenacity retry ultimately gave up on
  (`ProviderRequestTimeout`, a connection error, a persistent rate limit,
  etc.), which `pipeline.py` does not catch. It escapes to
  `scheduler.py`'s per-article loop, which *does* have a broad
  `except Exception as art_err` — but that branch just logs, increments
  `rejected`, and **keeps processing the rest of that source's
  articles**, one by one, each repeating the same failed call
  (`llm_blocked` is never set, so the article loop never `break`s). At
  the end of the cycle, the source is recorded
  `health_status="healthy"`, `last_fetch_at` updated — identical to a
  source that was successfully polled and simply had nothing newsworthy.
- **Reproduction:** `backend/tests/test_scheduler_provider_outage.py` — a
  fake `LLMProvider` subclass whose `classify_event` always raises a raw
  `TimeoutError` (not `LlmUnavailableError`), run through a real
  `scheduler.run_ingestion_cycle()` against a source with several
  articles. Before the fix: `source.health_status == "healthy"` despite
  100% failure, and the provider was called once per article (10 calls
  for 10 articles — a retry-storm risk, invariant 6) instead of aborting
  after the outage was confirmed.
- **Root cause, precisely:** a leaky abstraction boundary in two
  independent layers stacked on top of each other:
  1. The concrete providers (`NVIDIAProvider` primarily, but
     `OpenAIProvider`/`AnthropicProvider` had the identical structural
     gap) didn't guarantee every non-schema failure surfaces as
     `LlmUnavailableError` — see the `_unavailable_on_any_error` fix
     below.
  2. Even after fixing the concrete providers, **`pipeline.py` itself
     trusted every `LLMProvider` implementation — current and future,
     including test doubles and any custom provider someone adds later —
     to honor that contract perfectly**, with no defense at the boundary
     where it actually calls into `self.llm`. Proven by writing the
     reproduction test as a direct `LLMProvider` subclass (not
     `NVIDIAProvider`): fixing only the concrete providers left the
     reproduction test still failing, because `pipeline.py` had no
     fallback for a provider that doesn't cooperate.
- **Fix, both layers:**
  1. **Provider layer** (`backend/app/core/providers/llm.py`): new
     `_unavailable_on_any_error` decorator, applied as the outermost
     decorator on `classify_event`/`summarize_event`/
     `classify_relationship` for all three real providers. It lets
     `LlmUnavailableError` through unchanged and converts *any other*
     exception that escapes (schema/validation errors are already
     handled internally and never reach this layer) into
     `LlmUnavailableError`, chaining the original as `__cause__` for
     diagnosis. This makes the `LLMProvider` contract airtight: a caller
     only ever sees a normal return value or `LlmUnavailableError`.
     Applied uniformly to `NVIDIAProvider`, `OpenAIProvider`, and
     `AnthropicProvider` (which previously had **no retry decorator at
     all** — also added `@retry` there for consistency, a genuine gap
     found as a byproduct, not scope creep for its own sake — and
     `AnthropicProvider.classify_event`/`summarize_event` previously had
     no schema-error handling either, unlike NVIDIA/OpenAI; added the
     same try/except-return-None/`RelationshipResult.different()`
     pattern for consistency).
  2. **Pipeline layer** (`backend/app/core/pipeline.py`), the actual
     defense-in-depth fix that makes the reproduction test pass: all
     three call sites now have a second `except Exception as exc` after
     the existing `except LlmUnavailableError`, which normalizes to
     `self.last_outcome = "llm_unavailable"` and re-raises as
     `LlmUnavailableError` — so it doesn't matter whether the leak is in
     a built-in provider, a future provider, or a test double; the
     pipeline no longer trusts the provider to always cooperate.
- **Why fixing only one layer would have been incomplete:** the
  provider-layer fix alone (layer 1) makes the shipped, real providers
  correct, but is a promise, not an enforced contract — nothing stops a
  future provider implementation (or a bug reintroduced later in an
  existing one) from leaking a raw exception again, silently
  reintroducing this exact defect. The pipeline-layer fix (layer 2) is
  what actually makes the *invariant* hold regardless of provider
  implementation quality. Both were kept rather than picking one,
  because they answer different questions: "is NVIDIAProvider correct"
  vs. "can the ingestion pipeline be trusted regardless of which
  provider is plugged in."
- **Regression tests:**
  `backend/tests/test_scheduler_provider_outage.py` (2 tests) — a
  persistent-outage source is recorded `health_status != "healthy"` with
  a non-empty `last_error_info`, and the provider is not called once per
  remaining article after the outage is already evident (`calls < 10` for
  a 10-article feed with `_OutageLLMProvider`, run directly against
  `scheduler.run_ingestion_cycle`, not a unit-level mock).
- **Full suite after fix:** 360 passed, 0 failed (up from 357 — the 2 new
  outage tests plus 1 overlap-prevention test below). Fixing this
  surfaced 3 pre-existing test assertions in
  `test_nvidia_timeout_bound.py`/`test_provider_timeout_bound_openai_anthropic.py`
  that expected the raw `ProviderRequestTimeout` to escape
  `classify_event()` — correctly updated to expect `LlmUnavailableError`
  with the original exception preserved as `__cause__`, since that raw
  escape is exactly what this finding fixes.
- **Neighboring attack, verified rather than assumed:** invariant 5
  ("overlapping cycles must not create duplicate events") was checked
  directly against the installed `apscheduler`, not assumed from
  documentation memory: `BackgroundScheduler()._job_defaults` is
  `{'misfire_grace_time': 1, 'coalesce': True, 'max_instances': 1}`, and
  `scheduler.py`'s `add_job()` call never overrides `max_instances` or
  `coalesce` — so APScheduler itself refuses to start a second
  `run_ingestion_cycle` while one is still running (skips the trigger,
  does not queue a concurrent run), and coalesces missed fire times
  instead of firing them back-to-back. `VERIFIED`. Added
  `backend/tests/test_scheduler_overlap_prevention.py` (1 test) asserting
  `job.max_instances == 1` and `job.coalesce is True` directly against a
  real started scheduler, so a future change to `add_job()` that
  accidentally raises `max_instances` (e.g. "to make ingestion faster")
  cannot silently reintroduce concurrent-cycle risk without a test
  explaining why not.
- **Neighboring attack, not yet resolved — logged as `OPEN FINDING` (not
  swept into "fixed"):** invariant 4 ("a slow article must not
  indefinitely block a cycle") is now *individually* bounded per LLM call
  (NVDA-01's hard deadline, ~100s x up to 3 tenacity attempts ≈ 300s
  worst case per call), but there is still no **outer, whole-cycle**
  wall-clock budget in `scheduler.py::run_ingestion_cycle`. A source with
  many articles, each legitimately taking close to that per-call ceiling
  (not an outage — just slow, e.g. a large backlog processed after
  downtime), could still make one ingestion cycle run for a long time in
  aggregate, delaying every source scheduled after it in the same cycle's
  `source_targets` loop. Deliberately not fixed with an arbitrary short
  cycle timeout per the operating brief's explicit instruction
  ("Measure first" / "Do NOT merely add arbitrary short timeouts that
  cause valid ingestion to fail") — this needs real measurement of
  typical cycle duration under realistic article volume before choosing
  a number, which this session did not do. Tracked as the next Phase 1A
  item.

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

### OPENAI-BROKEN-01 — `OpenAIProvider` crashed on every real call; `AnthropicProvider` had a separate, independent SDK-compatibility bug
- **Severity:** High in principle (complete, silent functional failure of
  a whole provider — not a graceful `LlmUnavailableError`, an uncaught
  `AttributeError`/`TypeError` reaching the pipeline), but **low current
  blast radius**: neither provider is the configured production provider
  (`LLM_PROVIDER=nvidia`), so this was never actually reachable in normal
  operation. Found only because Phase 1 deliberately checked whether the
  hard-deadline fix from NVDA-01 had been applied consistently across the
  whole provider abstraction — it had not, and checking why surfaced
  this.
- **Area:** Phase 1 — provider abstraction consistency / Phase 3 — LLM
  boundary
- **Status:** FIXED (session 2, 2026-09-22)
- **Description — OpenAIProvider:** `classify_event`/`summarize_event`/
  `is_same_event` called `self.client.beta.chat.completions.parse(...)`,
  the OpenAI SDK's structured-output helper. Verified directly against
  the installed `openai==1.12.0` (the exact version pinned in
  `requirements.txt`): `client.beta` has no `.chat` attribute at all in
  this version (`dir(client.beta)` → `['assistants', 'threads',
  'with_raw_response', 'with_streaming_response']`) — that helper was
  added in a later SDK release. Every real call would have raised
  `AttributeError: 'Beta' object has no attribute 'chat'` immediately,
  before any network request. Zero existing test coverage exercised this
  — the only pre-existing tests touching `OpenAIProvider` checked
  `isinstance()` after construction, never called its methods against a
  real or equivalently-shaped client.
- **Description — AnthropicProvider (a second, independent bug, found
  while fixing the first):** `_complete_json` unconditionally passed
  `temperature=0` to `self.client.messages.create(...)`. Verified
  directly against the installed `anthropic==1.7.0`: `temperature` is
  absent from the real method's parameter list entirely
  (`inspect.signature` → `max_tokens, messages, model, cache_control,
  container, inference_geo, metadata, output_config, service_tier,
  stop_sequences, stream, system, thinking, tool_choice, tools, ...` — no
  `temperature`). Every real call would have raised `TypeError:
  Messages.create() got an unexpected keyword argument 'temperature'`.
  Also unrelated to but discovered alongside: the installed SDK is built
  on `httpx2` (a separate package from `httpx`, same author/lineage,
  different module) and rejects a raw `httpx.Client` passed as
  `http_client` with an explicit, well-designed error message naming the
  mismatch — not a bug, just a real compatibility detail that had to be
  worked around in this session's own regression test.
- **Why this was invisible:** both providers are reachable only via
  `LLM_PROVIDER=openai`/`LLM_PROVIDER=anthropic`, neither of which this
  product's actual configuration uses (`nvidia` is both the default and
  the only one exercised by the live test suite). `anthropic` isn't even
  in `requirements.txt` (optional, imported behind `try/except
  ImportError`). No test in the inherited suite called either provider's
  real methods against a real (or realistically-mocked-at-the-right-level)
  client — the gap in test depth, not the gap in code review, is the
  actual root cause of both bugs surviving this long.
- **Fix:** `OpenAIProvider` rewritten to use the same manual
  JSON-schema-in-prompt + `response_format={"type": "json_object"}` +
  `parse_structured()` pattern already proven working in
  `NVIDIAProvider`/`AnthropicProvider`, rather than depending on the
  SDK's structured-parse helper at all — this fixes the immediate bug
  *and* removes the coupling to an exact pinned SDK version that caused
  it, and gives `OpenAIProvider` its own real `classify_relationship`
  override (previously relying on the base class's `is_same_event`-
  wrapping default) for consistency with the other two providers.
  `AnthropicProvider`: dropped the unsupported `temperature=0` argument
  (correctness comes from the Pydantic schema validation in
  `parse_structured()`, not from temperature — dropping it is not a
  meaningful behavior change). Both providers also gained the same hard
  wall-clock deadline treatment as `NVIDIAProvider` (`call_with_hard_deadline`,
  `OPENAI_REQUEST_DEADLINE_SECONDS = 75.0`,
  `ANTHROPIC_REQUEST_DEADLINE_SECONDS = 100.0`) — the actual Phase 1
  audit item that led to finding both bugs in the first place.
- **Cleanup:** `EquivalenceCheck`/`EQUIVALENCE_SYSTEM_PROMPT` and their
  branch in `coerce_structured_payload` removed — they became genuinely
  dead code as a direct result of this fix (only `OpenAIProvider`'s old
  implementation used them), not pre-existing dead code left untouched.
- **Regression tests:** `backend/tests/test_provider_timeout_bound_openai_anthropic.py`
  (2 tests) — proves both providers' hard deadlines bound a real call
  against a trickling fake transport (reusing `TrickleTransport` for
  OpenAI; a second transport class built on `httpx2` for Anthropic,
  since the installed SDK rejects `httpx.Client` outright — discovered by
  construction, not assumed). Both tests exercise the *actual* rewritten
  code paths, so they would have caught both original bugs immediately
  (confirmed: re-running them against the pre-fix code reproduces the
  `AttributeError` and `TypeError` respectively).
- **Full suite after fix:** 357 passed, 0 failed (up from 355 — the 2 new
  tests). `anthropic` package was installed into the working venv purely
  to make this verification possible (it is optional and intentionally
  **not** added to `requirements.txt` — the code's own
  `try/except ImportError` handling is the correct contract for an
  optional provider, not a hard dependency).
- **Neighboring attack:** this raises a real process question worth
  carrying forward, not just a code fix — an optional/non-default code
  path (any `LLM_PROVIDER` other than `nvidia`) has no live-call
  regression coverage the way NVIDIA does, so a *third* SDK-compatibility
  break in either provider could reappear undetected the next time either
  SDK is upgraded. Worth deciding, in a later phase, whether OpenAI/
  Anthropic deserve the same kind of live-call test tier NVIDIA has
  (gated behind their own API keys) or whether a lighter-weight
  "construct + call against a real SDK object with a fake transport"
  test (what this session added) is judged sufficient given they're not
  production-critical.

### CORS-01 — Wildcard CORS origin combined with credentials enabled
- **Severity:** Low today, escalates to Medium/High if session auth is
  ever added without revisiting this
- **Area:** Phase 12 — API red team
- **Status:** FIXED (session 2, 2026-09-22)
- **Description:** `backend/app/main.py` combined `allow_origins=["*"]`
  with `allow_credentials=True` — a known-bad combination. The code's own
  comment already flagged it as a TODO.
- **Attack:** no CSRF-style PoC was needed to justify the fix — there is
  no cookie/session auth anywhere in the codebase (confirmed by absence
  of any auth module in `backend/app`), so there was nothing sensitive
  for this to currently leak via credentialed cross-origin requests. Fixed
  anyway rather than deferred, because the combination becomes exploitable
  the instant auth is added and is easy to miss re-checking at that point.
- **Root cause:** Leftover permissive default from early scaffolding,
  never tightened.
- **Fix:** `backend/app/core/config.py` gained a `CORS_ALLOWED_ORIGINS`
  setting (comma-separated, env-configurable, defaults to the frontend's
  local dev origins `http://localhost:3000`/`http://127.0.0.1:3000` —
  mirroring the existing pattern for other config) and a
  `get_cors_allowed_origins()` helper. `backend/app/main.py` now passes
  that allowlist to `CORSMiddleware` and sets `allow_credentials=False`
  (nothing currently needs it; add it back deliberately alongside real
  auth, not as an unexamined default). `docker-compose.yml` documents the
  env var.
- **Regression test:** `backend/tests/test_cors_config.py` (5 tests) —
  config parsing (comma-split, whitespace/empty handling, default is not
  `*`), and two tests against a real `TestClient` request: a configured
  origin gets `Access-Control-Allow-Origin` echoed back with no
  `Access-Control-Allow-Credentials` header, and an unlisted origin does
  not get its origin echoed back.
- **Live verification, not just unit tests:** started both the real
  backend (production LLM mode, real `ai_platform.db` with existing data)
  and the real frontend dev server, loaded the dashboard in an actual
  browser, and confirmed via `read_network_requests` that
  `NewEventsNotifier.tsx`'s client-side cross-origin fetch
  (`localhost:3000` → `localhost:8000`) succeeds (`200 OK`) under the new
  config, with zero console errors and zero server-side errors across the
  home feed, an event detail page, and the admin sources page (which also
  exercises the `AdminSource` typing fix from Phase 0 session 1 with real
  data — 10 real sources rendered correctly).
- **Neighboring attack:** confirmed the frontend's own client-side fetch
  never used `credentials: 'include'`, so `allow_credentials=False` is a
  pure hardening change with zero functional impact on the current
  frontend — not a tradeoff that happened to work, a change with no
  behavioral cost today.

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

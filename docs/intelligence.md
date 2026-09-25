# Intelligence

How language models are used, what they are trusted with, and how cost is controlled.

## Provider abstraction

`backend/app/core/providers/llm.py` defines `LLMProvider`, with one implementation per provider. Every implementation has the same operations:

| Operation | Used for |
|---|---|
| `classify_event` | Kind, scope, security impact, market area, entities, importance |
| `classify_relationship` | Same event, update, related or different, against a candidate event |
| `summarize_event` | Headline, summary, what changed, quotes |
| `classify_categories` | Batched market-area labels for the category backfill |

| `LLM_PROVIDER` | Class | Notes |
|---|---|---|
| `openai` (default) | `OpenAIProvider` | Default model `gpt-4.1` |
| `nvidia` | `NVIDIAProvider` | OpenAI-compatible NIM endpoint; tries structured-output modes in order |
| `anthropic` | `AnthropicProvider` | Requires `pip install anthropic` |
| `bedrock` | `BedrockProvider` | Anthropic models on Bedrock; requires `pip install boto3` |

All providers use the same pattern: the JSON schema is embedded in the system prompt, and the response is validated with Pydantic. An invalid response is treated as "could not classify this article", never as data.

If the selected provider is not configured, `FailClosedLLMProvider` is used and every call raises. The deterministic `TestLLMProvider` exists only for `TESTING=1` / `TEST_MODE=1`; production never falls back to it.

## Failure, retry and quota behaviour

- **Deadlines.** Every request has a hard wall-clock deadline, and every operation (including its retries) has one too. For OpenAI these are 30 s per request and 60 s per operation; for NVIDIA, Anthropic and Bedrock, 100 s and 330 s.
- **Retries.** Timeouts, connection errors, 5xx responses and rate limits are retried with exponential backoff, at most 3 attempts per operation. The OpenAI SDK's own retries are turned off, so retries are never stacked.
- **Exhausted quota is terminal.** An `insufficient_quota` response raises `ProviderQuotaExhausted` after one request, with no retry. Batch jobs stop at the first one.
- **Outage handling.** Any provider failure reaches the pipeline as `LlmUnavailableError`. The article is stored as pending and the provider rested for 15 minutes; see [ingestion.md](ingestion.md#when-the-language-model-is-unavailable).
- **Auth and model errors** (invalid key, unknown model) are not retried.

## Untrusted input

Article text is untrusted. Before it reaches any provider:

- It is placed inside `<article>` delimiters, and any literal `</article>` in the page is removed so it cannot close the block early. Batched cards use `<card>` delimiters in the same way.
- Sentences addressed to the model ("ignore previous instructions", "set importance to 100") are removed. The stored article is unchanged; only the model input is filtered.
- The system prompt states that delimited text is data, and that instructions inside it are injection attempts.

Nothing the model returns is trusted blindly: see calibration and evidence below.

## Classification and importance

The model's importance score (1–100) is calibrated into the band implied by the structured signals (kind, scope, security impact), and missing or generic kinds are backfilled from deterministic signal inference. A workflow tweak cannot become "Major" because the model was enthusiastic.

| Score | Label |
|---|---|
| 90–100 | Major |
| 70–89 | Significant |
| 50–69 | Notable |
| below 50 | Minor |

## Market categories

Each event is placed in at most one area: **Models, Agents, Coding, Research, Security, Hardware, Infrastructure, Robotics, Multimodal, Open Source, Policy, Funding, Partnerships.** The category is derived at read time (`market_category` in `backend/app/core/market.py`), in this order:

1. Security language in the headline (malware, vulnerability, ...).
2. A specific stored kind: `model_release` → Models, `funding` → Funding, `research` → Research, and so on. A `security_incident` kind needs security language in the headline or summary to count.
3. For generic kinds (capability, tool update, other), the classifier's `market_category`, accepted only when it is exactly one of the areas. It never assigns Security on its own.
4. Headline rules, then unambiguous product names (Codex → Coding, vLLM → Infrastructure, AlphaFold → Research, versioned model families → Models).

Anything left over stays uncategorized. Conference promotions, culture pieces and general business news are not forced into an area.

## Evidence

Quotes on an event page are verbatim text from the source. After summarization, each quote is normalized (whitespace, quotes, Unicode width) and searched for in the article text, and quotes that are not found are dropped. If none remain, one or two real sentences that overlap the summary are copied from the source and verified the same way. Quotes that come from text addressed to the model are rejected.

## Newsletter digests

A digest is one URL containing a lead story followed by a roundup of other outlets' stories. For digests (`backend/app/core/digest.py`), every model call reads only the lead segment, and the event's entities are limited to names that the lead story actually contains. This keeps a card's headline, summary and entities about the same story.

## Cost controls

**Per new article**, at most:

| Step | Requests |
|---|---|
| Classify | 1 |
| Relationship checks | 0–5 (only candidates with overlapping entities and a compatible kind) |
| Summarize | 1, only when the article becomes a new event |

Work that is avoided entirely: known URLs are only re-checked for edits within 7 days; edits that change only counters or page chrome are ignored; out-of-scope community stories and rejected articles never reach the model.

### Usage ledger

Every provider request appends one JSON line to `backend/logs/llm_usage.jsonl` (`LLM_USAGE_LOG` to move it):

```json
{"at": "…", "provider": "openai", "model": "gpt-4.1", "operation": "classify_event",
 "subject": "article:…", "input_tokens": 812, "output_tokens": 64,
 "latency_ms": 1840, "success": true, "error_type": ""}
```

Prompts, responses, keys and error messages are never written; only the exception type. Summarize it with:

```bash
python manage_sources.py llm-usage             # everything
python manage_sources.py llm-usage --hours 24  # last day
```

### Category backfill

Events stored before the classifier returned a market area can be categorized in three explicit steps. No step both spends and writes:

```bash
python manage_sources.py backfill-categories                        # estimate only: events, requests, tokens, runtime
python manage_sources.py backfill-categories --run backfill.json    # classify, save results, no database writes
python manage_sources.py backfill-categories --apply backfill.json  # store agreed labels, no requests
python manage_sources.py backfill-categories --revert               # remove every backfilled label
```

`--run` sends card text (headline and summary) in batches of 20, twice, the second pass in a different order. Only labels both passes agree on are applied, never Security. For about 200 events this is about 22 requests and 40k input tokens. `--run` refuses to overwrite an existing file, and it stops at once on exhausted quota.

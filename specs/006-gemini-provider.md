# Spec 006: Google Gemini provider

Status: Approved (2026-10-31, by the user's explicit approval; drafted 2026-10-30, last
revised 2026-10-31 after audits and the user's official checks). All decisions of
section 14 are approved: D2 (model) and D9 (role mapping) on 2026-10-30, D1, D3 to D8
and D10 on 2026-10-31, D11 (input estimate, closes Q11), D12 (transport reuse), D13
(usage folder paths), D14 (lone surrogates), D15 (missing project root), D16 (thought
marker), D17 (ledger write failures), D18 (`error.code` format) and D19 (`reason` on
`AIError`) on 2026-10-31. This approval covers the specification only. It
does **not** authorize implementation, which needs a separate explicit authorization
from the user. A first real call needs its own authorization after that, and gates G1
to G4 (section 9) are not verified. Gemini is not activated.
A preferred answer in section 15 is not an approval unless it cites an approved
decision.
Owner: DealPilot AI team
Depends on: spec 004 (AI provider layer), including amendment P4 (1 MiB response limit and
total request deadline, approved and implemented 2026-10-30). Restrictions on Meta are
**not** part of this spec: they are proposed separately as spec 004 amendment P5
(Proposed / Draft) and apply only if P5 is approved.

## 1. Goal and scope
Add Google Gemini as a third provider behind the spec 004 interface, so that:
- `mock` stays the default, offline and free, with no key;
- `meta` stays available as a secondary provider, unchanged by this spec;
- `gemini` becomes the intended main paid provider, selected only by configuration;
- business code (for example a future spec 005) never changes when the provider changes;
- spending is limited by a small monthly budget (at most 5 USD per UTC month) and an
  external cap at Google, without any absolute guarantee (section 7.5).

**Intended future uses** (each needs its own approved spec; this spec only provides the
provider):
- **A. Business summaries and metric explanations** (spec 005, Draft).
- **B. Analysis and interpretation of sales data** (no spec yet).

**Ground rule for both uses.** DealPilot's own engine produces every number, metric and
calculation. Gemini only receives structured results and explains them. It never
invents, recomputes or replaces reference data, and every statement it makes must be
traceable to the data it was given. How a business feature checks this (for example
spec 005's number validation and template fallback) belongs to that feature's spec.

**In scope (spec approved 2026-10-31; implementation needs a separate authorization):**
a `GeminiProvider` adapter, its settings, the cost guard (ledger and two-phase
reservation), error mapping and offline tests with fake transports.
**Not in scope:** any endpoint or spec 002 change, any business feature (spec 005 needs its
own approval), any change to Meta (spec 004 P5), streaming, tools (search, grounding, code
execution, function calling, URL context), files, images, audio, caching, retries,
automatic fallback between providers, any new dependency.

## 2. Google facts and traceability
Every fact below was checked on 2026-10-30, except F5 and F12 (2026-10-31). Facts are **not
permanent guarantees**: Google changes models, prices, limits and terms. "Not found on
the page read" never means "does not exist". Section 9 lists what must be checked again
before any first real call.

Readings recorded:
- **UR2:** the user's second consultation of the official pages, 2026-10-30. The
  reference for this spec.
- **UR1:** the user's first consultation, 2026-10-30 (pricing page only).
- **TR:** an earlier reading through an automated web tool that summarizes pages. Used
  only where no user reading exists, and marked as such.

### 2.1 Facts in use
| ID | Fact | Source and URL | Reading | What is confirmed | Limits of the check | Next action |
|---|---|---|---|---|---|---|
| F1 | REST call `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` | https://ai.google.dev/api/generate-content | TR | Endpoint pattern and method | Tool reading only | Confirm in G1 |
| F2 | Requests authenticate with the `x-goog-api-key` header | https://ai.google.dev/api | UR1 | Header name | None known | None; the key stays out of URLs (section 8) |
| F3 | Request: `contents[]` with roles `user` and `model`, which must **alternate**; `parts[].text`; `systemInstruction` (text only); `generationConfig` with `maxOutputTokens` and `temperature` | https://ai.google.dev/gemini-api/docs/generate-content/text-generation (alternation, UR2); https://ai.google.dev/api/generate-content (fields, TR) | UR2 and TR | `user` and `model` must alternate in `contents` | Field names from tool reading only | Mapping rule of section 4 (G5); confirm fields in G1 |
| F4 | Response: `candidates[].content.parts[].text`, `finishReason` (`STOP`, `MAX_TOKENS`, `SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII`, `OTHER`, `CONTINUATION` and others), `promptFeedback.blockReason`, `usageMetadata` with `promptTokenCount`, `candidatesTokenCount`, `thoughtsTokenCount`, `totalTokenCount` | https://ai.google.dev/api/generate-content (TR); `thoughtsTokenCount` also https://ai.google.dev/gemini-api/docs/generate-content/thinking (UR2) | UR2 and TR | `thoughtsTokenCount` is returned | Other fields from tool reading; the thought marker `parts[].thought` (boolean, "Indicates if the part is thought from the model") was read by tool on 2026-10-31 on the pages of section 2.3; the user's own review is pending | Confirm in G1 |
| F5 | `generateContent` error statuses documented: 400 (`INVALID_ARGUMENT`; `FAILED_PRECONDITION`, for example free tier not available in the country without billing), 402 (`RESOURCE_EXHAUSTED`, Prepay credits used up), 403 (`PERMISSION_DENIED`), 404 (`NOT_FOUND`), 429 (`RESOURCE_EXHAUSTED`, rate limits), 499 (`CANCELLED`), 500 (`INTERNAL`), 503 (`UNAVAILABLE`), 504 (`DEADLINE_EXCEEDED`); error body `error` with `code` (integer, the HTTP status code), `message` (string), `status` (string, gRPC code in `SCREAMING_CASE`) and `details` (array) | https://ai.google.dev/gemini-api/docs/generate-content/api-errors | TR (2026-10-31) | Statuses, their meanings and the field types of the error body | Tool reading only; whether each field is always present is not stated; 401, 416 and 3xx are not on this page (section 6 keeps them as DealPilot's own defensive rules); billing of failed requests not covered (F9 stays the source) | Confirm in G1 |
| F6 | `gemini-3.5-flash-lite`: stable, released 2026-07-21, no shutdown date announced; Standard 0.30 USD per 1M input tokens and 2.50 USD per 1M output tokens, thinking included | https://ai.google.dev/gemini-api/docs/pricing.md, https://ai.google.dev/gemini-api/docs/deprecations | UR2 | ID, status, dates, Standard prices | Prices change; account access not checked | Check prices again just before the first real call (G1) |
| F7 | `gemini-3.1-flash-lite`: stable, shutdown announced for 2027-05-07, Google recommends `gemini-3.5-flash-lite` instead; Standard 0.25 USD input and 1.50 USD output per 1M tokens | https://ai.google.dev/gemini-api/docs/pricing.md, https://ai.google.dev/gemini-api/docs/deprecations, https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite | UR2 | ID, status, shutdown date, replacement, prices | Prices change | None unless chosen |
| F8 | Thinking: `max_output_tokens` includes thinking tokens. When the limit is reached during reasoning, the result can be cut or empty, the status can be `MAX_TOKENS`, and the thinking tokens produced are still billed. `usageMetadata.thoughtsTokenCount` is returned | https://ai.google.dev/gemini-api/docs/generate-content/thinking | UR2 | The general API rule | The REST field to set the thinking level and the default level per model are not confirmed (Q2) | None for the bound; keep Q2 open |
| F9 | Billing: prepay with a 5 USD minimum for the setup concerned; manual top-up; optional automatic top-up; calls stop when the balance reaches zero. Billing can lag about 10 minutes, so the balance can be exceeded; spend caps can lag too. Requests that fail with HTTP 400 or HTTP 500 are not billed for the tokens used | https://ai.google.dev/gemini-api/docs/billing | UR2 | These rules in general | The operator's account, balance and settings were not seen; nothing is set up | Operator checks and sets up the account (G3) |
| F10 | Terms: paid-service data is not used to improve Google products; free-service data may be, and may be read by humans; for the EEA, Switzerland and the UK the paid-service rules apply even to some free uses, and apps offered to users there may use only paid services | https://ai.google.dev/gemini-api/terms, https://ai.google.dev/gemini-api/docs/billing | UR2 | These rules in general | Account and project tier not seen | Operator checks the project tier (G4) |
| F11 | Available regions include Angola | https://ai.google.dev/gemini-api/docs/available-regions | UR2 | General regional availability | Not a check of the operator's account or payment method | Operator checks account and payment (G3, G4) |
| F12 | Token counting: `countTokens` is a separate REST call (`POST .../v1beta/{model=models/*}:countTokens`); system instructions and tools are counted, roles are not mentioned; the docs give only an average ("a token is equivalent to about 4 characters") and no upper bound; whether `countTokens` is billed is not stated; the Google Gen AI SDK's local tokenizer is "[Experimental] Text Only", downloads tokenizer files, needs extra packages, does not count roles or turn formatting, and does not list `gemini-3.5-flash-lite` | https://ai.google.dev/gemini-api/docs/tokens, https://ai.google.dev/api/tokens, https://ai.google.dev/gemini-api/docs/pricing, https://ai.google.dev/gemini-api/docs/billing, https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite, https://github.com/googleapis/python-genai (`local_tokenizer.py`, `_local_tokenizer_loader.py`) | TR (2026-10-31) | No official local tokenizer or bound for this model | Tool reading only; support of `countTokens` for this model not stated | Basis of D11; the user may confirm by reading the pages (G1) |

### 2.2 History of readings (not for configuration)
| Reading | Content | Status |
|---|---|---|
| TR, 2026-10-30 | `gemini-3.5-flash-lite` stable at 0.30 / 2.50 USD, thinking on by default at `minimal` | Model and prices now confirmed by UR2 (F6). The default thinking level is still unconfirmed (Q2). |
| UR1, 2026-10-30, pricing page | `gemini-3.5-flash-lite` not presented; `gemini-3.5-flash` at 1.50 / 9 USD | Superseded by UR2, which presents `gemini-3.5-flash-lite`. `gemini-3.5-flash` is not a candidate. |
| TR, 2026-10-30 | `maxOutputTokens` bound on thinking not confirmed for `generateContent` | Superseded by UR2 (F8). |
| TR, 2026-10-30 | Batch and Flex prices about half of Standard | Unconfirmed; Batch and Flex are not in scope. |

### 2.3 Official Google references
Official pages of the `generateContent` API (labeled "Gemini Generate Content API
(Legacy)" by Google), read by an automated tool (TR) on 2026-10-31. They are references
only: they change no decision, criterion or gate, and G1 still needs its check just before
the first real call.

| Reference | What it documents | Decisions | What it does not confirm |
|---|---|---|---|
| https://ai.google.dev/gemini-api/docs/generate-content/thinking | Thought summaries are found by "checking the `thought` boolean" of each response part (enabled with `includeThoughts`); `max_output_tokens` includes thought tokens, and a limit reached while thinking ends with `MAX_TOKENS` and truncated or empty output, still billed; `thoughtsTokenCount` gives the thinking tokens; thinking levels (`thinkingConfig.thinkingLevel`, default `minimal` for 3.5 Flash-Lite) | D16 (thought marker); D7 (`MAX_TOKENS` with empty text); D11, only for the output part of the reservation (thinking counted in `max_tokens` and billed as output) | The UTF-8 input estimate of D11; whether thought parts appear when `includeThoughts` is not sent; a sentence on the marker specific to `gemini-3.5-flash-lite` |
| https://ai.google.dev/gemini-api/docs/generate-content/api-errors | Error body `error` with `code` (integer, "The HTTP status code"), `message` (string), `status` (string, gRPC code in `SCREAMING_CASE`) and `details` (array); statuses 400, 402, 403, 404, 429, 499, 500, 503 and 504 with their meaning (page updated 2026-10-27) | D18 (`error.code` is a whole number, so `reason` stays `None`); D7 (status classification); D19, only for the shape of `error.code` that leaves `reason` `None`; D17, only as the list of HTTP failures a call can return | Whether each error field is always present; statuses 401 and 416; the billing of failed requests (F9, from the billing page, stays the source); the local ledger rules of D17 and the `reason` attribute of D19, which are DealPilot design choices |

## 3. Architecture
```
DealPilot app (future approved feature)
  -> AI provider factory: dealpilot.ai.get_provider()
       -> Gemini  (future main paid provider)
       -> Meta    (secondary paid provider, unchanged unless spec 004 P5 is approved)
       -> Mock    (local, offline, the default)
```
- Reuses spec 004 as it is: `AIProvider.complete(CompletionRequest) -> CompletionResult`,
  `Message`, `Usage`, `Secret`, the `Transport` type, the default `https_transport` (P4
  size limit and total deadline), `REGISTRY` and the `AIError` classes.
- New `dealpilot/ai/gemini.py`: `GeminiProvider(AIProvider)`, `name = "gemini"`, with an
  injectable `Transport` like `MetaProvider`.
- **Transport reuse (D12).** `gemini.py` imports `Transport`, `https_transport`,
  `ResponseTooLarge` and `MAX_RESPONSE_BYTES` from `dealpilot/ai/meta.py`, where spec 004
  section 4.1 places the HTTPS transport. The transport is not moved, copied or wrapped
  in a new module, and no `transport.py` is created, so Gemini depends on the `meta`
  module. `meta.py`, its imports and its tests do not change, and importing it opens no
  connection (AC-GEM-24).
- New `dealpilot/ai/budget.py`: the ledger and the two-phase reservation (section 7).
- `dealpilot/ai/errors.py` (D19): `AIError` gets an optional keyword argument `reason`,
  default `None`, stored on the error. Existing constructions of `AIError` and its
  subclasses keep working unchanged, no caller has to pass `reason`, and existing error
  behavior does not change. The new `AIBlockedError` and `AIBudgetError` follow the
  same rule. `reason` never holds the key, request or body text, or confidential data.
- Documentation to update with the implementation: `docs/ai-providers.md`, with the two
  new error classes, the `reason` field and the lock procedure of section 7.4.
- `factory.REGISTRY` and `config.PROVIDERS` get `gemini`. The `AIProvider` interface, the
  API, its endpoints and spec 002 do not change. No module outside `dealpilot.ai` imports
  `gemini.py` or `budget.py`.

## 4. Message mapping
| DealPilot | Gemini |
|---|---|
| `system` messages | `systemInstruction.parts[]`, one text part per system message, in order. Allowed only before the first non-system message; otherwise `AIRequestError`. |
| `user` | `contents[]` item with `role: "user"` |
| `assistant` | `contents[]` item with `role: "model"` |
| `max_tokens` | `generationConfig.maxOutputTokens` |
| `temperature` | `generationConfig.temperature` |

**Role alternation (F3, rule D9, approved 2026-10-30).** `contents[]` must alternate
`user` and `model`. The mapping therefore:
1. merges each run of consecutive non-system messages with the same role into one
   `contents[]` item, with **one text part per original message**, in the original
   order, each text unchanged (no joining or trimming), so order and content are kept
   exactly;
2. refuses with `AIRequestError` a conversation whose first non-system message is
   `assistant`, because `contents[]` would then start with `model` (not representable
   under the alternation rule as read; to be lifted only if Google documents it).

The spec 004 contract does not change: `CompletionRequest` already requires the last
message to come from `user`, so `contents[]` always ends with `user`.

Never sent: a thinking-level field (Q2), `store` (Q5), `candidateCount`,
`tools`, `toolConfig`, `cachedContent`, `safetySettings` overrides and file parts.

**Response.** Only `candidates[0]` is read; any other candidate is ignored. Its text is the
concatenation, in order, of the parts that have a `text` field and are not marked as
thoughts; parts without text are skipped. The reply is then classified by section 6.

**Thought marker (D16).** The field that marks a part as a thought is not confirmed
(F4). The parser never guesses it:
1. The marker must be confirmed in Google's official documentation, with the page and
   date recorded (G1), before the part of the parser that skips thoughts is finished.
   This is a documentation check; it needs no API call.
2. Only parts that carry that confirmed official marker are skipped. Ordinary text is
   never dropped on a guess.
3. Until the marker is confirmed, no behavior is invented for it, and that part of
   AC-GEM-04 can't be finished. No thought data is ever shown as a reply to the user
   before its format is confirmed.
`usage.prompt_tokens` is `promptTokenCount`; `usage.completion_tokens` is
`candidatesTokenCount + thoughtsTokenCount` (what is billed, F8); `thoughtsTokenCount`
counts as 0 when absent.

## 5. Configuration
| Variable | Default | Rule |
|---|---|---|
| `DEALPILOT_AI_PROVIDER` | `mock` | `mock`, `meta` or `gemini`. A key being present never changes the provider (Q6). |
| `DEALPILOT_GEMINI_API_KEY` | none | Read only when the provider is `gemini`. Empty counts as not set (`AIConfigError` "is not set"); whitespace, control characters or fewer than 16 characters give "is malformed". Same `Secret` wrapper as the Meta key. `GEMINI_API_KEY` and `GOOGLE_API_KEY` are never read. |
| `DEALPILOT_GEMINI_MODEL` | none | **No default**: the operator must set it explicitly. Allowlist: `gemini-3.5-flash-lite` only (D2, approved 2026-10-30); any other value gives `AIConfigError`. Model, availability and prices are checked again before the first real call (G1). Another model needs a spec update. |
| `DEALPILOT_GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | https with a host, valid port; a final `/` is removed |
| `DEALPILOT_GEMINI_DATA_CLASS` | none | `synthetic` or `real`. Required for `gemini`: missing or any other value gives `AIConfigError`, so no Gemini call is possible (section 8). |
| `DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK` | none | Required for `gemini`. Decimal, strictly greater than 0 and at most 1,000, finite: the Standard price of the chosen model from the official pricing page. |
| `DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK` | none | Required for `gemini`. Decimal, strictly greater than 0 and at most 1,000, finite. |
| `DEALPILOT_GEMINI_PRICES_CHECKED_ON` | none | Required for `gemini`. ISO date of the official check, not in the future. |
| `DEALPILOT_AI_TIMEOUT_SECONDS` | `30` | Existing spec 004 setting (1 to 120): the total deadline per request (D3). |
| `DEALPILOT_AI_MAX_CALLS_PER_HOUR` | `30` | Paid providers only. May be set lower, never higher: whole number from 1 to 30 (fixed maximum 30). See "Fixed maximums" below. |
| `DEALPILOT_AI_USAGE_DIR` | `data/ai-usage` | Relative paths join the project root; absolute paths are used as given. Path rules in "Usage folder" below (D13). |

Prices have no default value: the operator sets the Standard prices of
`gemini-3.5-flash-lite` (D2) with their check date, after checking them again on the
official pricing page just before the first real call (G1). Nothing is configured or
activated automatically. A missing price or check date, or an invalid value, gives
`AIConfigError` naming the variable, when settings are loaded and before any ledger
read or network call. A price of 0 is invalid, like a negative one: it would make every
reservation 0 and turn off the budget. An invalid price is never replaced by 0 or by any
other default. `DEALPILOT_AI_MODEL` keeps its spec 004 meaning (Meta).

**Fixed maximums and lower operational limits (D4, D5).** For paid providers four
maximums are fixed in code: 16,000 input characters, 1,024 output tokens, 5 USD per UTC
month and 30 calls per hour. Raising any of them needs a new explicit decision and a
spec update. Operational settings may only **lower** them:

| Limit | Fixed maximum | Setting | Allowed values | Default |
|---|---|---|---|---|
| Input characters | 16,000 | `DEALPILOT_AI_MAX_INPUT_CHARS` | whole number, 1 to 16,000 | 16,000 |
| Output tokens | 1,024 | `DEALPILOT_AI_MAX_OUTPUT_TOKENS` | whole number, 1 to 1,024 | 1,024 |
| Monthly budget | 5 USD per UTC month | `DEALPILOT_AI_MONTHLY_BUDGET_USD` | decimal, 0 to 5.00 (0 blocks every paid call) | 5.00 |
| Calls per hour | 30 | `DEALPILOT_AI_MAX_CALLS_PER_HOUR` (already named in this spec) | whole number, 1 to 30 | 30 |

Validation rules:
1. A setting may be lower than or equal to its maximum; unset or empty means the default,
   which is the maximum.
2. A value outside its allowed range (below the minimum or above the maximum), a
   non-number, a non-whole number where a whole number is required, `nan` or `inf` is
   refused with `AIConfigError` naming the variable when settings are loaded, before any
   ledger read or network call.
3. An invalid value never falls back to the maximum or to any wider value: the paid
   provider can't be used until the setting is fixed.
4. `mock` reads none of these settings and has none of these limits.

The setting names and the minimums above were accepted by the user on 2026-10-31 as
documentation conventions. That acceptance was separate from the approval of D4 and D5
(2026-10-31, section 14). These settings can only lower the fixed maximums. To stop all
paid calls at once, set `DEALPILOT_AI_PROVIDER` to `mock`, or set
`DEALPILOT_AI_MONTHLY_BUDGET_USD` to 0.
Meta price variables belong to spec 004 P5, not to this spec.

**Usage folder (D13).** Checked when settings are loaded, only for `gemini`, with the
Python standard library only (no import of `dealpilot.analytics`, no DuckDB):
1. Values: `DEALPILOT_AI_USAGE_DIR` unset or empty means `data/ai-usage`. The data folder
   is `DEALPILOT_DATA_DIR`, unset or empty meaning `data/raw` (spec 002 section 3.2).
   `data/raw` always also means the project's own `<project root>/data/raw`.
2. Project root: as in spec 002 section 3.2, the first folder above the folder that holds
   the `dealpilot` package that contains `backend/pyproject.toml`.
3. An absolute path is used as given; a relative path joins the project root. The
   `data/raw` checks of rule 6 need the project root, so if no project root is found
   the `gemini` settings are refused with `AIConfigError` (D15), also when the usage
   folder and the data folder are both absolute. The `data/raw` protection is never
   turned off or skipped.
4. Ambiguous values are refused in **both** `DEALPILOT_AI_USAGE_DIR` and
   `DEALPILOT_DATA_DIR`: a NUL character, leading or trailing spaces, a leading `~`, and
   on Windows a drive without a root (`C:folder`) or a root without a drive
   (`\folder`). The `gemini` settings are then refused with `AIConfigError` naming the
   variable, before any ledger use. For `DEALPILOT_DATA_DIR` this is because the check
   can't be trusted; the API's own reading of that variable (spec 002) does not change.
5. Paths are resolved with symbolic links and Windows junctions followed for the parts
   that exist (`Path.resolve(strict=False)`) and compared after `os.path.normcase`, so
   case differences on Windows are ignored.
6. The usage folder is refused (`AIConfigError`) if it: is, or is inside, `data/raw`;
   contains `data/raw`, even when the configured data folder is elsewhere; is, or is
   inside, the configured data folder; contains the configured data folder; or exists
   and is not a folder.
7. Messages name the variable (`DEALPILOT_AI_USAGE_DIR` or `DEALPILOT_DATA_DIR`) and never
   show an absolute path. `mock` and `meta` never run these checks.
8. Known limit: a link created or changed after the check is not detected, so this
   protection can't be complete; it only covers the paths as they are when settings are
   loaded.

## 6. Errors and reply classification
New classes, both subclasses of `AIError`, so code that catches `AIError` keeps working:
`AIBlockedError` (content blocked by Google's rules) and `AIBudgetError` (local budget,
call limit, ledger or lock problem). `mock` raises neither. Meta raises neither unless
spec 004 P5 is approved.

| Case | Error |
|---|---|
| HTTP 3xx (redirects are never followed) | `AIProviderError` with the status |
| HTTP 400 | `AIProviderError` with the status. Never reported as a key problem. |
| HTTP 401 or 403 | `AIAuthError` |
| HTTP 402 (prepaid balance used up) | `AIBillingError` |
| HTTP 404 | `AIConfigError` ("model not found"), with the status |
| HTTP 416, 499, 5xx and any other non-2xx | `AIProviderError` with the status |
| HTTP 429 | `AIRateLimitError` |
| Total deadline passed (spec 004 D6) | `AITimeoutError` |
| Body over 1 MiB, error bodies included (spec 004 D5) | `AIResponseError` |
| Body not JSON, not an object, no candidates and no block reason, bad usage counts | `AIResponseError` |
| `promptFeedback.blockReason` set, or `finishReason` `SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT` or `SPII` | `AIBlockedError`, with the reason code only |
| `finishReason` `STOP` with non-empty text | success, `finish_reason="stop"` |
| `finishReason` `MAX_TOKENS` with non-empty text | success, `finish_reason="length"` |
| `finishReason` `MAX_TOKENS` with empty text (for example, thinking used the whole output) | `AIResponseError` |
| `finishReason` `CONTINUATION` (partial answer) | `AIResponseError`; a partial answer is never returned as a success |
| `finishReason` `OTHER`, missing, empty, or any value not in this table | `AIResponseError` |
| Empty or whitespace-only text with any success reason | `AIResponseError` ("empty reply") |

**Empty replies.** The rule above applies to Gemini. Spec 004 P5 proposes the same rule
for Meta; until P5 is approved, Meta keeps accepting `""` as today.

**Priority for a 2xx body (user decision 2026-10-31).** Invalid usage is checked first:
a body whose `usageMetadata` is present but invalid or incomplete (a missing, negative or
non-whole count) gives `AIResponseError`, even when it also has `blockReason` or a
blocked `finishReason`. With valid or absent usage, a block gives `AIBlockedError`. In
both cases the ledger rules of section 7.3 are unchanged (invalid usage: `kept`).

**Error body.** For non-2xx statuses the body (at most 1 MiB) is parsed only to read
`error.code`, kept on the error as `reason` when it is 1 to 64 characters of `a-z`, `0-9`
and `_`, and, for 400 and 500 only, `usageMetadata` for the ledger (section 7.3);
anything else is dropped. Classification uses the status only. `error.message`
and any other body text are never kept or shown. No text from the request, the key or the
URL appears in a message. No retry (D6).

**`error.code` format (D18).** The format of `error.code` is not confirmed (F5); it is
not assumed to be a whole number, and no other field (such as `error.status`) is
assumed to hold the reason. The format must be confirmed in Google's official
documentation during G1 (a documentation check, with no API call). Only a format that
is documented and confirmed is read; no mapping between `error.code`, `error.status`
and `reason` is invented. Until then, and for any value in another format, `reason` is
`None` and the error is classified by the status only (D7).

**Error body over 1 MiB.** If a response of any status, 400 and 500 included, has a body
over 1 MiB, reading stops and the result is `AIResponseError` (spec 004 D5), not the
status mapping above; neither `error.code` nor `usageMetadata` is read. Such a response is
not complete, so in the ledger it is never `not_billed`: the reservation is kept
(section 7.3).

## 7. Cost controls
These apply to `gemini` (and to `meta` only if spec 004 P5 is approved). `mock` has none
of these limits and never touches the ledger.

### 7.1 Limits (D4)
- Input: at most the configured input limit (fixed maximum 16,000 characters, section
  5), where a character is a Unicode code point as counted by Python `len()` on each
  message's `content`, summed over all messages (system included).
- Output: `max_tokens` at most the configured output limit (fixed maximum 1,024).
- Over either limit: `AIRequestError` before any ledger write or network call. Nothing is
  ever cut silently.
- Lone surrogate (D14): a message `content`, system included, that holds a lone
  surrogate (a code point from U+D800 to U+DFFF, which has no UTF-8 form) is refused
  with `AIRequestError`, the error used for invalid requests (spec 004 section 4.5),
  before any ledger read or write and before the transport is called. The content is
  never replaced, removed or changed. `mock` is not affected.
- Thinking (F8): `maxOutputTokens` includes thinking tokens, so under Google's documented
  rule the billed output of a call is at most `max_tokens`; the output part of the
  reservation (section 7.3) follows that rule. This is a **billing bound, not a promise
  of usable text**: if thinking uses the whole limit, the reply can be cut or empty
  (`MAX_TOKENS`), it is still billed, and section 6 turns it into `AIResponseError`. The
  ledger records the tokens Google reports, including `thoughtsTokenCount`. Because the
  thinking level can't be set yet (Q2), such empty replies are a known cost risk to watch
  in the ledger.

### 7.2 Ledger
- One file per UTC calendar month: `{DEALPILOT_AI_USAGE_DIR}/ledger-YYYY-MM.json`, plus
  `state.json` that records the first and the latest month written. Times are UTC ISO
  8601; the local time zone is never used.
- `state.json` holds `version`, `first_month`, `latest_month`, `months` and `updated_at`.
  `months` lists, sorted and without repeats, every month that has a ledger file; it is
  how phase 1 knows which monthly files must exist (section 7.3, step 1). Fail closed
  (user decision 2026-10-31): a ledger file with no `state.json`, a ledger file whose
  month is not in `months`, a month in `months` (current or previous) whose file is
  missing, inconsistent fields, or a time or month later than now make the ledger
  invalid, and every paid call is refused until a person repairs it
  (`docs/ai-providers.md`). Nothing is repaired automatically.
- Each entry: `id` (random), `provider`, `model`, `state` (`reserved`, `settled`, `kept`,
  `not_billed` or `released`), `created_at`, `updated_at`, `input_chars`,
  `input_bytes` (D11), `max_output_tokens`, `reserved_usd`, then when known
  `prompt_tokens`, `output_tokens` (candidates), `thoughts_tokens`, `cost_usd`, plus the
  prices and their check date used.
  Never prompts or replies.
- Money is computed with `Decimal` and stored as text with 6 decimals, rounded **up**
  (`ROUND_CEILING`, user decision 2026-10-31), so a stored reservation or cost is never
  lower than the exact amount. Each stored amount can be up to 0.000001 USD above it.
- Token fields record usage reported by Google; `cost_usd` records the estimated billed
  cost. They are different things: a `not_billed` entry can hold tokens with `cost_usd` 0.
- **Budget scope:** one monthly budget shared by all paid providers. Today only Gemini
  writes to it; Meta would join only under spec 004 P5.
- **Month total** = sum of `cost_usd` of `settled` entries plus sum of `reserved_usd` of
  `reserved` and `kept` entries. Each entry counts once, by its state only; `not_billed`
  and `released` entries count 0.
- **Fail closed:** a `settled` entry without a valid `cost_usd`, or a `reserved` or
  `kept` entry without a valid `reserved_usd`, makes the ledger invalid, and phase 1
  refuses every paid call with `AIBudgetError` (section 7.3, step 1).

### 7.3 Two-phase reservation
**Phase 1, before the call, under the exclusive lock (section 7.4):**
1. Read and validate `state.json`, the current month's ledger and the previous month's
   ledger (read for the hourly limit, step 2). The same checks apply to both ledger files.
   Refuse with `AIBudgetError` if: a file is unreadable, not valid JSON or has a bad
   shape; an entry has an unknown state, a negative amount, or a missing or invalid amount
   that its state needs (section 7.2); `state.json` says the current or the previous
   month was already written but its ledger file is missing; any entry or `state.json`
   time is later than now (clock moved back or file edited). If the previous month's
   ledger can't be trusted, the hourly limit can't be enforced, so the call is refused
   like for the current month; there is no automatic repair.
2. Hourly limit: count entries of any state except `released` (so `not_billed` calls
   count, since they were sent) with
   `now - 3600 s < created_at <= now`, across the current and previous month files. Refuse
   when the count already equals the configured hourly limit (at most 30; with the
   default, the 30th call in a window is allowed and the 31st is refused).
3. Reservation = estimated input tokens x input price + `max_tokens` x output price (per
   1M tokens). Estimated input tokens = `input_bytes` (D11): the sum, over all messages
   (system included), of the UTF-8 byte length of each message's `content`
   (`len(content.encode("utf-8"))`, strict). A content with a lone surrogate never
   reaches this step: it is refused before (section 7.1, D14). It is computed locally
   and deterministically: no network call, no
   `countTokens` call, no tokenizer and no new dependency, so the transport is still
   called once (AC-GEM-23). It is a **cautious estimate chosen by the operator, not a
   guaranteed bound and not a Google guarantee**: Google documents no local tokenizer
   and no upper bound for this model (F12). The tokens Google adds for roles, the
   `systemInstruction` and `contents` structure and any other formatting are **not**
   included; their number is unknown. `characters / 4` is not used. Section 7.5
   describes the risk of underestimation.
4. Budget: refuse when `month total + reservation > configured budget` (at most 5 USD);
   equal is allowed. A configured budget of 0 refuses every paid call.
5. Write the new `reserved` entry durably: write a temporary file, flush and `os.fsync`
   it, then `os.replace` it over the ledger; update `state.json` the same way. If any of
   these writes, replacements or validations fails without stopping the process (D17),
   the call is refused with `AIBudgetError` and the transport is never called (fail
   closed). Nothing is released or removed to tidy up: whatever is on disk stays as it
   is (the previous ledger, or a `reserved` entry that keeps counting as spent until a
   person checks it).
6. Release the lock.

**Phase 2:** the network call, without holding the lock.

**Phase 3, after the call, under the lock:**
Rules are applied in this order:
- 2xx response with valid `usageMetadata` (even when the reply is then refused by
  section 6, for example blocked or empty): the entry becomes `settled` with the reported
  tokens and the real cost `prompt_tokens x input price + (candidates + thoughts) x
  output price`.
- Status exactly **400** or exactly **500**, with a body that was read completely
  (within 1 MiB), is valid JSON and holds a valid `usageMetadata`: the usage is used to
  reconcile the reservation. Because Google's billing page says these two failures are
  not billed for the tokens used (F9), the entry becomes `not_billed` with `cost_usd` 0.
  The reported tokens are recorded as **usage data only**; they are never turned into a
  billed cost. This applies only to these two statuses, as F9 covers them, and never on
  the status code alone. No billing rule beyond F9 is assumed.
- Status 400 or 500 whose body is incomplete, over 1 MiB, unreadable, not valid JSON, or
  without a valid `usageMetadata`: the entry becomes `kept`. A missing `usageMetadata` is
  never taken as proof that nothing was billed.
- Timeout, network error, disconnection, any other HTTP error (including 503 and 504),
  unreadable body, or no valid `usageMetadata`: the entry becomes `kept` and its
  `reserved_usd` stays counted as spent. The billing of these cases is not documented
  (Q7), so every request that may have been sent and billed is treated as spent.
- `released` (counts 0) only when it is certain the request was never handed to the
  transport (the transport was never called).
- **Lock busy in phase 3** (another process holds it past the 5 s wait, section 7.4):
  nothing is written, the entry stays `reserved` (counted at its `reserved_usd`) and the
  call result is still returned. The ledger stays valid, so later calls keep counting the
  entry as spent; it changes only after a person's check (below).
- **Ledger not trusted in phase 3** (unreadable, or failing a step 1 check): nothing is
  written, the entry stays as phase 1 wrote it (`reserved`) and the call result is still
  returned. The next phase 1 refuses every paid call until a person fixes the ledger.
- **Write failure in phase 3** (D17): the response was received, but writing the
  reconciliation (temporary file, `os.fsync`, `os.replace` or `state.json`) fails
  without stopping the process. The entry keeps its last durably written state
  (`reserved`, counted at its `reserved_usd`); it is not settled, released or marked
  `not_billed`. The Gemini result already received is returned to the caller as
  section 6 classifies it (a reply, or the error from the response itself); it is never
  turned into a network error, and the request is never sent again. A reconciliation
  failure is a ledger problem, not a request failure. If the ledger is then invalid or
  unreadable, the next phase 1 refuses every paid call until a person repairs it.
- In all these cases an entry is never settled, released or marked `not_billed` without
  the lock, a valid ledger and a durable write.

**Crashes.** Each step leaves a safe state:
- crash in phase 1 before `os.replace`: no entry, no call was made, an orphan temporary
  file may remain;
- crash after phase 1 or during the call: the `reserved` entry stays counted as spent;
- crash in phase 3 before `os.replace`: the entry stays `reserved` (counted as spent).

`reserved` entries are never released automatically. A person may mark one `kept` or
`released` only after checking Google's usage page.

### 7.4 Lock and temporary files
- Lock file `{DEALPILOT_AI_USAGE_DIR}/ledger.lock`, created with
  `os.open(..., O_CREAT | O_EXCL | O_WRONLY)`. It holds JSON with the process id, host
  name, UTC creation time and phase (1 or 3). It is held only during phases 1 and 3, never
  during the network call.
- If the lock exists, the caller retries every 100 ms for up to 5 seconds, then refuses
  with `AIBudgetError("usage ledger is busy")` (zero transport calls).
- A lock is **never** removed automatically, even when old. After a crash, every paid
  call stays blocked until a person checks, from the pid, host and time in the lock, that
  no DealPilot process is still using it, and deletes the lock file. This procedure goes
  into `docs/ai-providers.md` with the implementation.
- Temporary files are named `ledger-YYYY-MM.json.tmp-<pid>-<id>` and `state.json.tmp-...`
  and are never read as a ledger. Under the lock, phase 1 deletes orphan temporary files
  of the usage folder: they never hold committed data, because only `os.replace` commits.
- On Windows `os.fsync` on the folder is not available; durability of the rename is then
  best effort (a known limit).

### 7.5 Limits of the local guard and the external cap
The local guard reduces, but can't rule out, spending above the budget:
- it is not tamper-proof: deleting or editing the usage folder resets it;
- Google's billing month and time zone may differ from the UTC month;
- Google may bill differently from `usageMetadata`, or bill interrupted requests (Q7);
- prices change; the ledger uses the configured prices and their check date;
- **the input estimate can be too low**: the UTF-8 byte count (D11) is an estimate, not
  a bound. The real token count can exceed it, for example through the tokens added for
  roles, the system instruction and the request structure (not included), or through
  the provider's tokenization rules, which Google does not document. A call can then
  cost more than its reservation. Reconciliation with valid `usageMetadata` (section 7.3)
  records the real cost afterwards, so later calls see it, but calls already reserved are
  not stopped. There is therefore **no mathematical guarantee** that real spend stays
  under the local cap;
- a 400 or 500 counted as `not_billed` relies on Google's billing page (F9); a reply
  without valid usage data keeps its reservation, because the absence of usage data is
  not proof that nothing was billed.

**External cap at Google (F9, gate G3).** The wanted setup is a **5 USD prepaid balance
with automatic top-up turned off**; Google stops calls when the balance reaches zero.
It is **not an instant hard cap**: Google says billing can lag about 10 minutes, so the
balance can be exceeded, and spend caps can lag too. The local ledger and the two-phase
reservation therefore stay mandatory. Nothing is set up: the operator must check and set
the balance and the top-up option in their own Google account before activation. A
billing alert is useful but is not a cap.

**Free tier.** The ledger counts free-tier calls at the configured paid prices. This is
deliberately cautious: the free tier may then stop at a 5 USD equivalent.

### 7.6 Cost estimate (illustration; prices to check again before the first real call)
Standard prices of the UR2 reading (F6, F7), to check again before the first real call.
Typical call: 1,500 input and 400 output tokens. Reservations use the UTF-8 byte
estimate (D11, not a guaranteed bound) plus 1,024 output tokens: 16,000 ASCII characters
count 16,000 bytes; the largest possible reservation is 16,000 characters of 4 bytes
each, so 64,000 bytes.

| Model (D2 status) | Typical cost per call | Calls for 5 USD | Reservation, 16,000 ASCII characters | Calls for 5 USD | Largest reservation, 64,000 bytes | Calls for 5 USD |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` (approved model, D2; 0.30 / 2.50) | 1,500 x 0.30 / 1M + 400 x 2.50 / 1M = 0.00145 USD | about 3,448 | 16,000 x 0.30 / 1M + 1,024 x 2.50 / 1M = 0.00736 USD | about 679 | 64,000 x 0.30 / 1M + 1,024 x 2.50 / 1M = 0.02176 USD | about 229 |
| `gemini-3.1-flash-lite` (comparison only, not chosen; shutdown 2027-05-07, 0.25 / 1.50) | 1,500 x 0.25 / 1M + 400 x 1.50 / 1M = 0.000975 USD | about 5,128 | 16,000 x 0.25 / 1M + 1,024 x 1.50 / 1M = 0.005536 USD | about 903 | 64,000 x 0.25 / 1M + 1,024 x 1.50 / 1M = 0.017536 USD | about 285 |

The hourly limit only limits bursts (30 per hour is up to 21,600 calls a month); the
monthly budget and the external cap are what bound spend. Lower operational settings
(section 5) reduce these figures.

## 8. Security, privacy and data class (Q3)
- Key only in the `x-goog-api-key` header, never in the URL, so it can't leak through
  logged URLs or error text. HTTPS with certificate checks; spec 004 P4 limits apply (DNS
  is not covered by the deadline).
- The layer does not log. The ledger holds counts and costs only.
- **Data class rule:** synthetic DealPilot data may be used for free-tier trials; real or
  confidential data only on the paid tier (F10).
- DealPilot **can't** tell which Google tier a key belongs to, where users are, or what
  kind of data a prompt holds. `DEALPILOT_GEMINI_DATA_CLASS` is therefore a **declaration
  by the person who configures DealPilot**, not a check:
  - `synthetic`: the operator declares that only synthetic data will be sent;
  - `real`: the operator declares that the key belongs to a paid-tier project and that the
    Google terms in force, the company's own rules and the EEA, Switzerland and UK rules
    were checked before;
  - missing or any other value: every Gemini call is refused (`AIConfigError`).
- **Users in the EEA, Switzerland or the UK** need the paid service, as Google's terms
  say (F10); this must be checked again before any activation that serves them.
- **Regions:** Angola is in Google's list of available regions (F11). This is general
  availability only; the operator's account and payment method are not validated.
- `mock` sends nothing anywhere.

## 9. Activation gates (before any first real call)
A first real call needs, in this order: approval of this spec (given 2026-10-31),
authorization to implement it (not given), the implementation with its offline tests
passing, and a separate explicit authorization for the call. Gate status on 2026-10-30:

| Gate | What must be true | Status | Basis | Next action |
|---|---|---|---|---|
| G1 | Model ID, availability and Standard prices; request, response and error fields | **Partly confirmed.** Model IDs, status, dates and Standard prices of both Flash-Lite models confirmed officially (F6, F7). Request, response and error fields still rest on tool reading (F1, F3 to F5), except alternation and `thoughtsTokenCount`. The thought marker `parts[].thought` (section 2.3) and the error body format (F5) are documented on official pages read by tool on 2026-10-31; the user's own review of these pages is pending | F1 to F7 | D2 approved 2026-10-30 (`gemini-3.5-flash-lite`); check the model, its availability, the prices and the fields again just before the first real call; confirm, with page and date recorded, the thought-part marker (D16) and the `error.code` format (D18), which is a documentation check and may be done before implementation |
| G2 | Billed output is bounded by `maxOutputTokens` | **Confirmed officially** for the general API rule (F8). Not a guarantee of usable text (section 7.1) | F8 | None for the bound; watch empty `MAX_TOKENS` replies in the ledger |
| G3 | 5 USD prepaid balance without automatic top-up, available for the account | **Confirmed in general** (prepay, 5 USD minimum, manual and automatic top-up, stop at zero, about 10 minutes of billing lag, F9). **To check in the operator's Google account**; not set up. Not an instant hard cap | F9, F11 | Operator sets the balance and turns automatic top-up off |
| G4 | Data handling on the paid tier and the applicable terms; data class declared | **Confirmed in general** (F10). **To check in the operator's Google account** (project tier); `DEALPILOT_GEMINI_DATA_CLASS` is an operator declaration | F10 | Operator confirms the project tier before declaring `real` |
| G5 | Consecutive same-role messages | **Requirement confirmed** (alternation, F3). **Transformation approved** (section 4, D9, 2026-10-30); resolved once its tests (AC-GEM-03) pass | F3 | Implement and test D9 once the spec is approved and implementation is authorized |

The `x-goog-api-key` header (F2) matches sections 3 and 8: the key is sent only in that
header, never in a URL.

## 10. Compatibility
- `mock` behaves exactly as today and has no paid-provider limits.
- `meta` behaves exactly as today. Any change to Meta needs spec 004 P5.
- Callers switch providers only with `DEALPILOT_AI_PROVIDER`.
- `gemini` is language-neutral: it sends the messages it receives and adds no language
  instruction. The output language is set by each business feature (DealPilot is
  English-only, `AGENTS.md`; spec 005 D6).
- `mock` accepts a conversation whose first non-system message is `assistant`; `gemini`
  refuses it with `AIRequestError` (D9). This is a constraint of the Gemini provider; it
  does not change the spec 004 `CompletionRequest` contract or the v1 API.
- Spec 005 (Draft, use A) could use `gemini` with no business code change, but only once
  spec 005 itself is approved. Use B (sales analysis and interpretation) has no spec yet.
  Approving this spec does not authorize any business feature.

## 11. Acceptance criteria (mandatory since the global approval of 2026-10-31)
The spec was approved as a whole on 2026-10-31, so every criterion below is mandatory
for the implementation, once implementation is authorized.

Tests in `backend/tests/test_ai_gemini.py` (G) and `test_ai_budget.py` (B), named
`test_ac_gem_NN_...`, with fake transports, a fake clock, temporary folders and subprocesses
where noted. No network and no real key.

| ID | Criterion (observable result) | File |
|---|---|---|
| AC-GEM-01 | Settings: section 5 defaults (no model and no prices by default; `gemini-3.5-flash-lite` is accepted and any other model value gives `AIConfigError`); each invalid value raises `AIConfigError` naming the variable; an empty key gives "is not set"; a key with a space, a tab or another control character, or with fewer than 16 characters, gives "is malformed"; with only `GEMINI_API_KEY` or `GOOGLE_API_KEY` set, the key is reported as not set; the key never appears in `repr` or `str`; a Gemini key alone leaves the provider `mock`. | G |
| AC-GEM-02 | The fake transport records `POST {base}/models/{model}:generateContent` with `{model}` = `gemini-3.5-flash-lite`, for a base URL with and without a final `/`; headers hold `x-goog-api-key` with the key and `Content-Type: application/json`, and no `Authorization`; the URL has no query; the body has exactly `contents`, `generationConfig` and, when present, `systemInstruction`, with no thinking-level, `store`, `candidateCount`, `tools` or `safetySettings` field. | G |
| AC-GEM-03 | Two system messages become two `systemInstruction` parts in order; a system message after a user message raises `AIRequestError`; `assistant` becomes `model`; user, user, assistant, assistant, user becomes three `contents[]` items (`user` with 2 parts, `model` with 2 parts, `user` with 1 part) with every text unchanged and in order; a conversation whose first non-system message is `assistant` raises `AIRequestError` before any ledger write or transport call. | G |
| AC-GEM-04 | A valid response gives the expected text from the text parts of `candidates[0]`, skipping only parts that carry the thought marker confirmed in Google's official documentation (D16): this part waits for that confirmation, its test data follows the confirmed format, and no text is dropped on a guess; a second candidate and parts without text are ignored; `STOP` gives `"stop"`; usage is prompt tokens and candidates + thoughts tokens, with thoughts 0 when absent; with `MAX_TOKENS` and only thinking used (empty text) the reply is refused but the entry is `settled` with its billed thoughts tokens. | G, B |
| AC-GEM-05 | Statuses 301, 400, 401, 402, 403, 404, 416, 429, 499, 500, 503 and 504 give the section 6 errors with the status kept; `reason` is set only from an `error.code` in the format confirmed in Google's official documentation (D18) that also meets section 6; any other value, and every value while the format is unconfirmed, gives `reason` `None` with classification by status only; `reason` never holds the key or body text; errors built without `reason` keep working (D19); messages never hold `error.message`, body text, the key or the URL; with a fake connection and a fake clock, reads that together pass `DEALPILOT_AI_TIMEOUT_SECONDS` give `AITimeoutError` through `GeminiProvider` even when each read is shorter (shared total deadline, D3), and no Gemini-only timeout setting exists. | G |
| AC-GEM-06 | With valid or absent usage, `blockReason` and each of `SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII` give `AIBlockedError` with that reason code; `OTHER`, an unknown value, an empty value and a missing `finishReason` give `AIResponseError`. | G |
| AC-GEM-07 | Not JSON, a JSON list, no candidates without a block reason, bad usage counts (checked first: also when the body has `blockReason` or a blocked `finishReason`, and the reservation is kept) and a body over 1 MiB (also with status 500) give `AIResponseError`. | G |
| AC-GEM-08 | Empty text and whitespace-only text with `STOP`, `MAX_TOKENS` with empty text, and `CONTINUATION` give `AIResponseError`; `MAX_TOKENS` with text gives `"length"`. | G |
| AC-GEM-09 | With default settings, 16,000 characters pass and 16,001 are refused, counting code points (a 4-byte emoji counts 1) across all messages, and `max_tokens` 1,024 passes and 1,025 is refused; with lower settings (for example 10,000 characters and 512 tokens) the boundaries move down the same way; settings of 1 character and 1 token are accepted; a setting of 0, above 16,000 or above 1,024, a negative, non-whole, `nan` or non-numeric value gives `AIConfigError` and is never widened; a message, system included, holding a lone surrogate (for example `"\ud800"`) gives `AIRequestError` before any ledger read or write and transport call, with the content unchanged (D14); refusals happen before any ledger write or transport call; `mock` accepts 16,001 characters and `max_tokens` 4,096. | G |
| AC-GEM-10 | Budget: with `month total + reservation` exactly equal to the configured budget (5 USD by default, or a lower setting such as 2 USD) the call runs; 0.000001 USD more is refused with `AIBudgetError` and zero transport calls; a budget setting of 0 refuses every paid call; a budget setting above 5.00, negative or invalid gives `AIConfigError`; a non-fatal failure while writing the reservation in phase 1 (temporary file, `os.fsync`, `os.replace` or `state.json`) gives `AIBudgetError` with zero transport calls and no entry released (D17); `mock` never reads or writes the ledger. | B |
| AC-GEM-11 | Hourly limit with a fake clock: with the default, the 30th call in a window runs and the 31st is refused; with a setting of 10, the 11th is refused; a setting of 31, 0, a negative or a non-whole value gives `AIConfigError`; an entry exactly 3,600 s old no longer counts; `released` entries never count. | B |
| AC-GEM-12 | The transport spy reads the ledger during the call and finds a `reserved` entry with `input_bytes` equal to the UTF-8 byte count of all message contents (an ASCII letter counts 1, a 4-byte emoji counts 4) and `reserved_usd = input_bytes x input price + max_tokens x output price` (per 1M tokens, D11), and no lock file; the transport is called once and no `countTokens` URL is ever called. | B |
| AC-GEM-13 | After a valid response the entry is `settled` with prompt, output and thoughts tokens and the real cost; after a blocked or empty reply with valid usage it is also `settled`; an entry counts as `settled` only once that state is durably written (D17). | B |
| AC-GEM-14 | A 400 or 500 whose body is read completely and holds a valid `usageMetadata` gives `not_billed` with the reported tokens recorded as usage data and `cost_usd` 0 (counts 0 in the month total, 1 in the hourly count); a 400 or 500 with no `usageMetadata`, an invalid one, an unreadable or non-JSON body, or a body over 1 MiB gives `kept` at `reserved_usd`; a 2xx response with no `usageMetadata`, an invalid one (for example a missing, negative or non-integer count), or an unreadable, incomplete, non-JSON or over 1 MiB body gives `kept` at `reserved_usd`, never `settled` with an assumed cost; a timeout, a network error, a 503, a 504 and another 4xx give `kept`; `released` happens only when the transport was never called; no entry becomes `settled`, `not_billed` or `released` without a durable write (D17). | B |
| AC-GEM-15 | Crash simulation: stopping after phase 1 leaves a `reserved` entry that the next call counts; a failure between the temporary write and `os.replace` leaves the previous ledger intact, and the next phase 1 deletes the orphan temporary file; when the lock can't be taken in phase 3 (held lock, 5 s on the fake clock), the call result is still returned and the entry stays `reserved`, counted at its `reserved_usd` (fail closed): it is never settled, released or marked `not_billed` without the lock; when the ledger is unreadable or invalid in phase 3, nothing is written, the call result is still returned and the next phase 1 refuses with `AIBudgetError` and zero transport calls; a non-fatal write failure in phase 3 leaves the entry `reserved`, returns the Gemini result (reply or response error) unchanged rather than a network error, makes no second transport call, and, when the ledger is left invalid or unreadable, the next phase 1 refuses until a person repairs it (D17). | B |
| AC-GEM-16 | Two subprocesses share one usage folder with a budget that fits exactly one reservation: exactly one transport call happens and the other gets `AIBudgetError`. | B (subprocess) |
| AC-GEM-17 | A held lock makes the caller wait, then after 5 s (fake clock) refuse with `AIBudgetError` and zero transport calls; an old lock is never deleted automatically; the lock holds pid, host, UTC time and phase. | B |
| AC-GEM-18 | At a UTC month boundary (fake clock, any `TZ` value) a new month file is used; a `reserved` entry of the previous month stays in that month; the hourly window spans both files. | B |
| AC-GEM-19 | An entry or `state.json` time later than now, invalid JSON, a wrong shape, an unknown state, a negative amount, a `settled` entry without a valid `cost_usd`, a `reserved` or `kept` entry without a valid `reserved_usd`, an unreadable file, and a missing current-month or previous-month file that `state.json` says exists each give `AIBudgetError` with zero transport calls, whether the problem is in the current month's ledger or in the previous month's ledger. | B |
| AC-GEM-20 | Usage folder (D13), with a temporary fake project root: the default resolves to `<root>/data/ai-usage`; a usage folder that is, is inside or contains `data/raw` (also written `DATA/RAW` on Windows, or with `..`), that is, is inside or contains the configured data folder, or that exists as a file gives `AIConfigError`; so does a link or junction to such a folder (skipped where links can't be created); with no project root, `AIConfigError` is raised, also when the usage and data folders are both absolute, so the `data/raw` checks are never skipped (D15); in `DEALPILOT_AI_USAGE_DIR` and in `DEALPILOT_DATA_DIR`, a NUL, leading or trailing spaces, a leading `~`, `C:folder` or `\folder` give `AIConfigError` naming the variable, before any ledger use; messages name the variable and hold no absolute path; `mock` and `meta` ignore an invalid usage folder. | B |
| AC-GEM-21 | Prices: a missing price or check date, a zero, a negative, non-numeric, `nan` or `inf` price, or a missing, invalid or future check date gives `AIConfigError` before any ledger read or transport call, and is never replaced by 0 or a default; each entry stores the prices and check date used. | G |
| AC-GEM-22 | `DEALPILOT_GEMINI_DATA_CLASS` missing or not `synthetic` or `real` gives `AIConfigError` for `gemini` and has no effect on `mock` or `meta`. | G |
| AC-GEM-23 | A Gemini error never leads to a call to another provider and the transport is called exactly once (no retry). | G |
| AC-GEM-24 | Importing the layer opens no connection (subprocess with sockets disabled); the API app has no new route; Meta's current empty-reply behavior is unchanged (its AC-AI-08 case still passes until spec 004 P5 is approved). | G |

## 12. Dependencies
None new: standard library only (`http.client`, `ssl`, `json`, `os`, `decimal`,
`pathlib`). No tokenizer or Google SDK (D11).

## 13. Relation with spec 004
- Uses spec 004 unchanged, including amendment P4. The HTTPS transport is imported from
  `meta.py`, where spec 004 places it (D12); spec 004 is not amended.
- Adds `gemini` to `DEALPILOT_AI_PROVIDER`, the errors `AIBlockedError` and
  `AIBudgetError` to the layer (spec 004 section 4.5) and the optional keyword argument
  `reason` to `AIError` (D19, backward compatible), only once implementation of this
  spec (approved 2026-10-31) is authorized. Spec 004 itself is not amended.
- Every change to Meta (limits, prices, shared budget, empty replies) is in spec 004 P5,
  which needs its own approval. P5's decisions are cited here as P5-D7 to P5-D10, to keep
  them apart from this spec's D7 to D10.

## 14. Decisions (D2 and D9 approved 2026-10-30; all others 2026-10-31)
| ID | Decision | State |
|---|---|---|
| D1 | Gemini is a separate spec (006). Changes to Meta are a separate spec 004 amendment (P5). | Approved 2026-10-31 by the user's explicit decision |
| D2 | Model: `gemini-3.5-flash-lite` (stable, released 2026-07-21, no shutdown date, Standard 0.30 USD input and 2.50 USD output per 1M tokens, thinking included; F6). Chosen over `gemini-3.1-flash-lite`, which is cheaper but has a shutdown date of 2027-05-07 and for which Google recommends this model instead (F7). Allowlist of this one model; no default value; Gemini is not activated. The model, its availability and its prices must be checked again before the first real call (G1). | Approved 2026-10-30 by the user's explicit decision |
| D3 | Reuse the shared spec 004 total deadline (`DEALPILOT_AI_TIMEOUT_SECONDS`); no Gemini-only timeout. | Approved 2026-10-31 by the user's explicit decision |
| D4 | Fixed maximums for paid providers: 16,000 input characters (Unicode code points) and 1,024 output tokens; operational settings may only lower them (validation in section 5; an invalid value is refused, never widened); requests over the configured limit are refused, never cut; `mock` exempt; raising a maximum needs a new explicit decision. G2 is confirmed (F8), which is not an authorization for real calls. | Approved 2026-10-31 by the user's explicit decision |
| D5 | Local budget with a fixed maximum of 5 USD per UTC month and a fixed maximum of 30 calls per hour, shared by paid providers; operational settings may only lower them (section 5); raising a maximum needs a new explicit decision. UTC monthly ledger; two-phase reservation with the proposed input estimate of 1 token per character, which is not a guaranteed bound and must be validated before implementation; reconciliation with valid `usageMetadata` (on 2xx, and on 400 or 500 only with a complete, readable body and valid usage, then `not_billed` per F9: tokens kept as usage data, cost 0); keep the reservation whenever the request may have been sent and no valid usage proves otherwise; exclusive lock never removed automatically; refuse paid calls on any doubt; no absolute financial guarantee (section 7.5); external 5 USD prepaid balance without automatic top-up wanted, not an instant cap (G3). | Approved 2026-10-31 by the user's explicit decision |
| D6 | No automatic retry and no automatic fallback to another provider. | Approved 2026-10-31 by the user's explicit decision |
| D7 | Errors and reply classification as in section 6 (400 gives `AIProviderError`; `MAX_TOKENS` without text, `CONTINUATION`, `OTHER`, unknown reasons and empty replies give `AIResponseError`). | Approved 2026-10-31 by the user's explicit decision |
| D8 | `DEALPILOT_GEMINI_DATA_CLASS` is a required operator declaration (`synthetic` or `real`); without it, Gemini calls are refused. | Approved 2026-10-31 by the user's explicit decision |
| D9 | Role alternation: consecutive same-role messages are merged into one `contents[]` item with one part per message, order and text unchanged; a conversation starting with `assistant` is refused (section 4). | Approved 2026-10-30 by the user's explicit decision |
| D10 | Future uses A (business summaries) and B (sales data interpretation): DealPilot computes every number; Gemini only explains structured results and never invents or recomputes data; each use needs its own approved spec. | Approved 2026-10-31 by the user's explicit decision |
| D11 | Input estimate (closes Q11): the UTF-8 byte count of all message contents, computed locally (section 7.3, step 3). It replaces the proposed factor of 1 token per character in D5; the rest of D5 is unchanged. No network call, no `countTokens`, no tokenizer or SDK, no new dependency; one transport call. A cautious estimate chosen by the operator, not a guaranteed bound or a Google guarantee; formatting tokens are not included and unknown; reconciliation with valid `usageMetadata` stays mandatory. | Approved 2026-10-31 by the user's explicit decision |
| D12 | Transport reuse (option A1): `gemini.py` imports `Transport`, `https_transport`, `ResponseTooLarge` and `MAX_RESPONSE_BYTES` from `meta.py`; no `transport.py`, no move or copy of the transport; spec 004 is not amended or reinterpreted; Meta's imports and tests do not change. | Approved 2026-10-31 by the user's explicit decision |
| D13 | Usage folder paths: standard library only; relative paths join the project root and are refused with `AIConfigError` when no root is found; absolute paths are used as given; links and Windows case are handled; the usage folder is refused if it is, is inside or contains `data/raw` or the configured data folder (section 5, "Usage folder"); a link changed after the check is a known limit. | Approved 2026-10-31 by the user's explicit decision |
| D14 | Complements D11: a message `content` with a lone surrogate (U+D800 to U+DFFF) has no UTF-8 form, so it is refused with `AIRequestError` before any ledger read or write and before the transport; the content is never replaced or changed; the byte count uses strict UTF-8 (sections 7.1 and 7.3). | Approved 2026-10-31 by the user's explicit decision |
| D15 | Complements D13: if the project root can't be found, the `data/raw` checks can't be made, so `gemini` settings are refused with `AIConfigError`, also when the usage and data folders are both absolute; the `data/raw` protection is never turned off; messages name the variable and show no absolute path (section 5, "Usage folder", rule 3). | Approved 2026-10-31 by the user's explicit decision |
| D16 | Thought marker: never guessed; it must be confirmed in Google's official documentation (G1, documentation check) before the thought-skipping part of the parser is finished; only parts with the confirmed marker are skipped; ordinary text is never dropped on a guess; no thought data is shown as a reply before its format is confirmed (section 4). | Approved 2026-10-31 by the user's explicit decision |
| D17 | Ledger write failures that don't stop the process: in phase 1 the call is refused with `AIBudgetError` and the transport is not called; in phase 3 the entry keeps its last durable state (`reserved`), the Gemini result already received is returned as section 6 classifies it, the request is not sent again, and an invalid or unreadable ledger blocks paid calls until a person repairs it (section 7.3). | Approved 2026-10-31 by the user's explicit decision |
| D18 | `error.code` format: not assumed (not assumed to be a whole number, no reason taken from another field); confirmed in the official documentation during G1; only a confirmed format is read; until then `reason` is `None` and the status alone classifies the error (D7) (section 6). | Approved 2026-10-31 by the user's explicit decision |
| D19 | `AIError` gets an optional keyword argument `reason` (default `None`); existing constructions of `AIError` and its subclasses, including `AIBlockedError` and `AIBudgetError`, keep working; no caller must pass it; `reason` never holds the key or confidential data; `docs/ai-providers.md` is updated with the implementation (sections 3 and 13). | Approved 2026-10-31 by the user's explicit decision |

Conditions kept with these approvals (2026-10-31):
- D5 and D11: the input estimate is the UTF-8 byte count (D11, which closes Q11 and
  replaces the proposed factor of 1 token per character); it is not a guaranteed bound;
  the local 5 USD budget is not a mathematical guarantee on real billing (section 7.5).
- **Method in force.** The method in force is the UTF-8 byte count of D11, completed by
  D14. The words of D5 about "1 token per character" and its validation are kept only
  as the record of the initial decision; they are not the method in force, and no
  section or acceptance criterion uses them.
- D13 and D15: the `data/raw` protection is never turned off; without a project root,
  `gemini` settings are refused.
- D4 and D5: the fixed maximums (16,000 input characters, 1,024 output tokens, 5 USD
  per UTC month, 30 calls per hour) can only be lowered by settings, never raised.
- D7: errors and reconciliation follow section 6 and F9 (section 7.3), unchanged.
- D8: the data class stays an operator declaration; the Google account checks are not
  done.
- Gates G1 to G4 (section 9) are not verified or met; they stay required before any
  real call. These approvals do not authorize implementation or a real call.

## 15. Questions
| ID | Question | Preferred answer (2026-10-30; not an approval unless it cites an approved decision) |
|---|---|---|
| Q1 | What must be checked again before the first real call? | The list of gate G1, on the official pages, with the date recorded. |
| Q2 | Which REST field sets the thinking level? | Open (optional). Not confirmed. No thinking-level field is sent until confirmed; the model default applies. Known risk: billed empty `MAX_TOKENS` replies (section 7.1). |
| Q3 | Free or paid tier? | Free tier with synthetic data only; real or confidential data on the paid tier only (section 8). Covered by D8 (approved 2026-10-31). |
| Q4 | Monthly budget? | Covered by D5 (approved 2026-10-31): fixed maximum of 5 USD per UTC month, lower settings allowed (section 5), with a 5 USD prepaid balance without automatic top-up wanted as the external cap (G3, not verified). |
| Q5 | Send the `store` field? | No. |
| Q6 | Mock still the default when a Gemini key is present? | Yes. |
| Q7 | Does Google bill failed or interrupted requests? | Partly answered: complete 400 and 500 failures are not billed (F9). Timeouts, disconnections and other statuses are undocumented and treated as spent. |
| Q8 | Does `maxOutputTokens` bound thinking tokens? | Yes, as a general API rule (F8, G2). Covered by D4 (approved 2026-10-31). |
| Q9 | Are consecutive same-role messages accepted? | No: roles must alternate (F3). Covered by D9 (approved 2026-10-30), mapping rule of section 4. |
| Q10 | Which Gemini model? | Answered by D2 (approved 2026-10-30): `gemini-3.5-flash-lite`, to be checked again before the first real call. |
| Q11 | How is the input estimate of the reservation validated? | Closed by D11, completed by D14 (both approved 2026-10-31 by the user's explicit decision): the UTF-8 byte count of all message contents, computed locally. Google documents no local tokenizer and no upper bound for this model (F12), so the method is a cautious estimate, not a guaranteed bound and not a Google guarantee; formatting tokens are not included and unknown. |

# Spec 004: AI provider layer

Status: Approved (2026-10-30, by the user's explicit approval). Assumptions A1 to A5 stay
unverified until Q1 is closed.
Owner: DealPilot AI team
Depends on: `AGENTS.md` (Stack: LLM features are optional add-ons; the MVP works without
them). Independent of specs 001, 002 and 003.

## 1. Goal
A small internal library, `dealpilot.ai`, that lets future business features ask a
language model for text through one common interface, so that:
- everything works locally with a **mock provider**, with no API key and no network;
- a **Meta Model API** adapter is ready for when access is available, without any change
  to the code that uses the layer;
- another provider can be added later by writing one adapter class and registering it.

## 2. Non-goals
- No new HTTP endpoint and no change to any spec 002 contract. Spec 002 section 2 says
  "no Meta or other LLM APIs" for the v1 API; this spec does not change that.
- No business feature uses the layer yet. No change to analytics, the generator or any
  calculation.
- No forecasting. Spec 003 and its O2 restrictions are untouched.
- No new dependency. The Meta adapter uses the standard library (`http.client`, `json`,
  `ssl`). `httpx` stays a dev-only dependency.
- No `.env` loading. Settings come from the process environment only; no `.env` file is
  read or written by the code.
- No real call to the Meta API in tests or in this task.
- No streaming, tool calls, images, embeddings, retries or caching in this version.

## 3. Assumptions (unverified, to confirm before activation)
These could not be checked without network access. The adapter keeps them in one place
(`dealpilot/ai/meta.py`) so they are easy to fix.

| ID | Assumption |
|---|---|
| A1 | The base URL is `https://api.meta.ai/v1`. |
| A2 | Requests use `POST {base_url}/chat/completions` with a JSON body `{"model", "messages": [{"role", "content"}], "max_tokens", "temperature"}` and the header `Authorization: Bearer <key>`. |
| A3 | A success response is JSON with `choices[0].message.content` (string), optional `choices[0].finish_reason` (string), optional `model` (string) and optional `usage` with integer `prompt_tokens` and `completion_tokens`. |
| A4 | The model ID `muse-spark-1.3` exists. |
| A5 | Status codes: 401 and 403 mean a rejected key; 402 means billing or payment; 429 means a rate limit; 5xx means a server error. |

## 4. Design

### 4.1 Package layout
`backend/src/dealpilot/ai/`, a new domain module next to `data`, `analytics` and `api`:

| File | Content |
|---|---|
| `__init__.py` | Public names: types, errors, `load_settings`, `get_provider` |
| `types.py` | `Message`, `CompletionRequest`, `CompletionResult`, `Usage` (frozen dataclasses) |
| `errors.py` | Error classes (section 4.5) |
| `config.py` | `AISettings`, `load_settings`, the model list, the secret wrapper |
| `base.py` | `AIProvider`, the common contract |
| `mock.py` | `MockProvider` |
| `meta.py` | `MetaProvider` and its HTTPS transport |
| `factory.py` | Provider registry and `get_provider` |

### 4.2 Common contract
- `Message(role, content)`: `role` is `system`, `user` or `assistant`; `content` is a
  non-empty string.
- `CompletionRequest(messages, max_tokens=512, temperature=0.0)`: at least one message,
  the last one from `user`; `max_tokens` from 1 to 4,096; `temperature` from 0.0 to 2.0.
  Invalid values raise `AIRequestError` when the request is built.
- `AIProvider` has a `name` and one method `complete(request) -> CompletionResult`.
- `CompletionResult(text, provider, model, finish_reason, usage)`: `text` is a string;
  `usage` is `Usage(prompt_tokens, completion_tokens)` or `None`.
- Business code depends only on these types, `get_provider` and the error classes, never
  on a concrete provider.

### 4.3 Configuration (environment variables)
| Variable | Default | Rule |
|---|---|---|
| `DEALPILOT_AI_PROVIDER` | `mock` | `mock` or `meta` |
| `DEALPILOT_AI_MODEL` | `muse-spark-1.3` | One of the supported models (`muse-spark-1.3` only for now) |
| `DEALPILOT_AI_TIMEOUT_SECONDS` | `30` | Number from 1 to 120. Total deadline for one request (D6, section 8). |
| `DEALPILOT_META_BASE_URL` | `https://api.meta.ai/v1` | Must start with `https://` and have a host |
| `DEALPILOT_META_API_KEY` | none | Read only when the provider is `meta` |

- Empty values count as not set. Any invalid value raises `AIConfigError` naming the
  variable, never its value when the variable is the key.
- The mock provider never reads `DEALPILOT_META_API_KEY`; a missing or bad key never
  affects it.
- For `meta`, a missing key raises `AIConfigError` ("DEALPILOT_META_API_KEY is not set").
  A key is malformed when it is shorter than 16 characters or contains whitespace or
  non-printable characters; that also raises `AIConfigError`. A well-formed key that the
  server rejects is reported by the adapter (section 4.5).
- The key is held in a wrapper whose `repr` and `str` show `'**********'`. The real value
  is used only to build the `Authorization` header.
- `load_settings(env=None)` reads `os.environ`, or the given mapping (for tests).

### 4.4 Providers
- **Mock:** deterministic, offline, no randomness. The reply is
  `"[mock:<model>] " + <last user message>` (first 200 characters). `finish_reason` is
  `"stop"` and `usage` counts whitespace-separated words. Same request, same result.
- **Meta:** builds the request of A2 and sends it with an injectable transport. The
  default transport is `http.client.HTTPSConnection` with the default SSL context
  (certificates verified) and the configured timeout. The response is validated as in A3.
  Since amendment P4 (section 8) the default transport also caps every body at 1 MiB and
  treats the timeout as a total deadline.
  Tests always inject a fake transport.
- **Registry:** `get_provider(settings=None)` picks the class by name from one dictionary.
  Adding a provider means adding an adapter class and one registry entry.

### 4.5 Errors
All errors derive from `AIError`. Messages never contain the API key, the request body or
the raw response body.

| Error | When |
|---|---|
| `AIConfigError` | Unknown provider or model, bad timeout or base URL, missing or malformed key |
| `AIRequestError` | Invalid `Message` or `CompletionRequest` |
| `AIAuthError` | HTTP 401 or 403 |
| `AIBillingError` | HTTP 402 |
| `AIRateLimitError` | HTTP 429 |
| `AIProviderError` | Any other non-2xx status, or a network error |
| `AITimeoutError` | The request timed out |
| `AIResponseError` | The body is not JSON, does not match A3, or is over 1 MiB (any status, error bodies included; section 8, D5) |

Each error carries the provider name and, for HTTP errors, the status code. The layer
does not log.

## 5. Acceptance criteria
Tests go in `backend/tests/test_ai_*.py` and are named `test_ac_ai_NN_...`. No test opens
a network connection.

| ID | Criterion |
|---|---|
| AC-AI-01 | With no `DEALPILOT_AI_*` variables set, settings give provider `mock`, model `muse-spark-1.3`, timeout 30 and the default base URL. |
| AC-AI-02 | Invalid provider, model, timeout (text, 0, 121) or base URL (`http://`, no host) each raise `AIConfigError` naming the variable. |
| AC-AI-03 | The mock provider works with no key, an empty key and a malformed key, and returns the same result for the same request. |
| AC-AI-04 | For `meta`, a missing key and a malformed key each raise `AIConfigError`; the key value never appears in the message. |
| AC-AI-05 | `repr` and `str` of settings never contain the key. |
| AC-AI-06 | Invalid messages and requests (empty list, bad role, empty content, last message not from `user`, `max_tokens` 0 or 4,097, `temperature` -0.1 or 2.1) raise `AIRequestError`. |
| AC-AI-07 | The Meta adapter sends `POST {base_url}/chat/completions` with the A2 body, the bearer header and the configured timeout, using a fake transport. |
| AC-AI-08 | A valid A3 response gives the matching `CompletionResult`. |
| AC-AI-09 | Status 401, 403, 402, 429, 500 and 418 map to the errors of section 4.5 with the status code; the key and the response body are not in the message. |
| AC-AI-10 | A transport timeout gives `AITimeoutError`; a network error gives `AIProviderError`. |
| AC-AI-11 | Non-JSON bodies, a JSON list, missing `choices`, empty `choices`, non-string content and non-integer usage each give `AIResponseError`. |
| AC-AI-12 | `get_provider` returns `MockProvider` or `MetaProvider` by setting; a new provider registered in the registry is returned without changing calling code. |
| AC-AI-13 | Importing `dealpilot.ai` opens no network connection and the API app registers no new route. |
| AC-AI-14 | Section 8, D5 (amendment P4). |
| AC-AI-15 | Section 8, D6 (amendment P4). |

## 6. Decisions
| ID | Decision | State |
|---|---|---|
| D1 | The layer is an internal library in `dealpilot.ai`; no endpoint, no API contract change. | Approved 2026-10-30 |
| D2 | No new dependency; the Meta adapter uses the standard library. | Approved 2026-10-30 |
| D3 | Default provider is `mock`; Meta is used only when `DEALPILOT_AI_PROVIDER=meta`. | Approved 2026-10-30 |
| D4 | Settings come from environment variables only; `.env.example` at the project root documents them with empty values. | Approved 2026-10-30 |

## 7. Open questions
| ID | Question |
|---|---|
| Q1 | Confirm A1 to A5 against Meta's API documentation before the first real call. |
| Q2 | Which business feature uses the layer first, and under which spec. |
| Q3 | Closed 2026-10-30: the user approved amendment P4 (D5 = A, D6 = A), section 8. |
| Q4 | Approve the proposed amendment P5 (section 9): paid-provider controls for Meta. |

## 8. Amendment P4: response size limit and total deadline
Prepared 2026-10-30 at the user's request as a proposal. Approved by the user on
2026-10-30 (D5 = A, D6 = A) and implemented the same day in the default transport
(`https_transport`) and `MetaProvider`. The Meta wire format itself is still unverified
against the real API (A1 to A5, Q1).

**Problem.** The default HTTPS transport reads the whole response body with no size limit,
and the configured timeout applies to each network operation (connect, each read), not to
the whole request. A slow or very large response can hold a caller far longer than
`DEALPILOT_AI_TIMEOUT_SECONDS` and use unbounded memory.

**Rules (approved).**
- **Response size limit:** at most 1 MiB (1,048,576 bytes) of response body. The body is
  read in chunks; the first byte past the limit stops the read and raises
  `AIResponseError` ("response too large"), with no part of the body in the message.
  Why 1 MiB: the largest allowed answer is 4,096 tokens, about 16 KiB of text; JSON
  overhead is small, so 1 MiB leaves a wide margin while bounding memory.
- **Total request deadline:** `DEALPILOT_AI_TIMEOUT_SECONDS` (default 30, range 1 to 120)
  becomes the deadline for the whole request: connect, send and the full body read. The
  connect step (TCP and TLS handshake) runs on its own with the time left at the start;
  after it, the socket gets the time still left before the request is sent, before the
  response headers are read and before each body read. The deadline is checked after
  every phase; when no time is left the request stops with `AITimeoutError`. It is never a
  fresh 30-second timeout per step. No new setting is added. Why: one number the caller
  can rely on; 30 seconds is the existing default. (Clarified 2026-10-30, correction A1:
  connect and send were first done in one step with the full initial timeout.)
- **Known limits:** DNS resolution in the standard library is not covered by socket
  timeouts, so a slow name lookup can take longer than the deadline. Inside the connect
  step, each socket operation of the TCP connect and TLS handshake is limited by the time
  left at the start, and the deadline is checked right after the step. No thread or
  dependency is added to work around either limit.
- A `Content-Length` above the limit is refused before reading, the body is read in
  chunks of at most 64 KiB, and the connection is closed on every path. `MetaProvider`
  also refuses a body over the limit from an injected transport.
- Both limits live in the default transport; the transport interface (section 4.4) is
  unchanged, so fake transports in tests keep working.

**Acceptance criteria.**

| ID | Criterion |
|---|---|
| AC-AI-14 | With a fake HTTPS connection: a body of exactly 1 MiB is accepted, read in chunks of at most 64 KiB; 1 MiB + 1 byte is refused, and through `MetaProvider` gives `AIResponseError` for success and error statuses alike, without the key, request or body in the message; a `Content-Length` above 1 MiB is refused before any read; the connection is closed every time. |
| AC-AI-15 | With a fake HTTPS connection and a fake clock: reads that together pass the deadline stop the request (`AITimeoutError` through `MetaProvider`) even when each read is shorter than the timeout; each socket operation gets the time left; a slow request phase also times out; the connection is closed every time. |

**Decisions.**

| ID | Decision | State |
|---|---|---|
| D5 | Response body limit of 1 MiB in the default transport, error bodies included. | Approved 2026-10-30 (option A) |
| D6 | `DEALPILOT_AI_TIMEOUT_SECONDS` is a total deadline per request, not a per-operation timeout (default 30 s, range 1 to 120). | Approved 2026-10-30 (option A) |

## 9. Proposed amendment P5: paid-provider controls for Meta (Proposed / Draft)
**State: Proposed / Draft, not approved.** Prepared 2026-10-30 at the user's request, so
that changes to Meta are not hidden inside spec 006. Nothing in this section applies
today: Meta keeps exactly the behavior of sections 4 to 8 until P5 is approved, and no
code or test changes until then. The status of spec 004 as a whole stays Approved.

**Why.** Spec 006 (Draft) proposes a shared cost guard for paid providers. Meta is a paid
provider, but its prices are unknown (A1 to A5 are unverified), so its spend can't be
estimated or capped today.

**Proposals.**
1. **Limits for paid providers.** Meta requests would be refused, never cut, above 16,000
   input characters (Unicode code points as counted by Python `len()`, summed over all
   messages) or above 1,024 output tokens (`max_tokens`). Today Meta accepts `max_tokens`
   up to 4,096 (section 4.2), so this narrows its contract. `mock` stays exempt.
2. **Prices.** Two settings, both required for a paid Meta call:
   `DEALPILOT_META_PRICE_INPUT_USD_PER_MTOK` and `DEALPILOT_META_PRICE_OUTPUT_USD_PER_MTOK`
   (USD per 1M tokens, decimal numbers from 0 to 1,000, finite, no sign), plus
   `DEALPILOT_META_PRICES_CHECKED_ON` (ISO date, not in the future). One price set without
   the other, a bad number or a bad date raises `AIConfigError` naming the variable. While
   the prices are not set, every paid Meta call is refused with `AIBudgetError` (spec 006).
3. **Budget scope.** Meta spend would go into the same local ledger and the same monthly
   budget as Gemini (`DEALPILOT_AI_MONTHLY_BUDGET_USD`, spec 006 section 7): one budget
   shared by all paid providers. The Google prepaid balance does not cover Meta, so for
   Meta the local ledger would be the only cap.
4. **Empty replies.** A reply whose text is empty or only whitespace would raise
   `AIResponseError` ("empty reply"), the same rule as spec 006. Today Meta accepts `""`
   as a valid reply (AC-AI-08 tests it), so this changes current behavior.
5. **Errors.** `AIBudgetError` (spec 006) would become a possible Meta error.

**Compatibility.** P5 needs spec 006's ledger and errors, so it can only be implemented
together with or after spec 006. The `AIProvider` interface, the API and spec 002 do not
change. Callers that catch `AIError` keep working.

**Proposed acceptance criteria.**

| ID | Criterion |
|---|---|
| AC-AI-16 | A Meta request of 16,001 characters or `max_tokens` 1,025 raises `AIRequestError` before any transport call; 16,000 and 1,024 pass; `mock` accepts both larger values. |
| AC-AI-17 | With either Meta price unset, a paid Meta call raises `AIBudgetError` and the transport records zero calls; one price set alone, a negative, non-numeric or non-finite price, or a bad check date raises `AIConfigError`. |
| AC-AI-18 | A Meta call is reserved, reconciled and counted in the shared monthly budget exactly as a Gemini call (spec 006 section 7). |
| AC-AI-19 | A Meta reply with empty or whitespace-only text raises `AIResponseError`; AC-AI-08's empty-content case is updated to expect it. |

**Proposed decisions.**

| ID | Decision | State |
|---|---|---|
| D7 | Paid-provider input and output limits apply to Meta. | Proposed |
| D8 | Paid Meta calls are refused until both Meta prices and their check date are configured. | Proposed |
| D9 | Meta spend shares the spec 006 ledger and monthly budget with Gemini. | Proposed |
| D10 | Empty or whitespace-only replies raise `AIResponseError` for Meta. | Proposed |

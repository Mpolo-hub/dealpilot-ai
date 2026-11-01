# AI Providers

How to use the AI provider layer (`dealpilot.ai`, specs `specs/004-ai-provider-layer.md`
and `specs/006-gemini-provider.md`). The layer is an internal library. No API endpoint uses
it yet, and the MVP works without it (`AGENTS.md`).

## Use the mock provider (default)
The mock provider needs no API key and no network. It is used whenever
`DEALPILOT_AI_PROVIDER` is unset, empty or `mock`.

```python
from dealpilot.ai import CompletionRequest, Message, get_provider

provider = get_provider()  # reads the environment; mock by default
result = provider.complete(CompletionRequest([
    Message("system", "You are a sales analyst."),
    Message("user", "Summarize last month's sales."),
]))
print(result.text)  # "[mock:muse-spark-1.3] Summarize last month's sales."
```

The reply is deterministic: the same request always gives the same result.

## Configure the Meta Model API later
1. Confirm assumptions A1 to A5 in spec 004 section 3 against Meta's documentation
   (open question Q1). The wire format lives only in `backend/src/dealpilot/ai/meta.py`.
2. Set the variables in your shell (PowerShell). Never write the key into a tracked file:
   ```powershell
   $env:DEALPILOT_AI_PROVIDER = "meta"
   $env:DEALPILOT_AI_MODEL = "muse-spark-1.3"
   $env:DEALPILOT_META_API_KEY = Read-Host "Meta API key"
   ```
   Optional: `DEALPILOT_AI_TIMEOUT_SECONDS` (total timeout for the whole request, 1 to 120,
   default 30) and `DEALPILOT_META_BASE_URL` (https only, default `https://api.meta.ai/v1`).
3. Call `get_provider()` as above. No business code changes.

A missing or malformed key raises `AIConfigError` when settings load. A key the server
rejects raises `AIAuthError`; a billing problem raises `AIBillingError`. See
`.env.example` for every variable.

## Configure Google Gemini (spec 006)
Gemini is a paid provider. It is used only when `DEALPILOT_AI_PROVIDER=gemini`: a Gemini
key alone never activates it, and `GEMINI_API_KEY` and `GOOGLE_API_KEY` are never read.
There is no automatic retry and no automatic fallback to another provider. **A first real
call needs the gates of spec 006 section 9 (G1 to G4) and a separate authorization.**

Settings, all required for `gemini` and read only then:

| Variable | Rule |
|---|---|
| `DEALPILOT_GEMINI_API_KEY` | At least 16 characters, no space or control character. Never write it into a tracked file. |
| `DEALPILOT_GEMINI_MODEL` | `gemini-3.5-flash-lite` only (D2); no default. |
| `DEALPILOT_GEMINI_DATA_CLASS` | `synthetic` or `real`: your declaration of what you send (D8). `real` only on a paid-tier project. |
| `DEALPILOT_GEMINI_PRICE_INPUT_USD_PER_MTOK`, `DEALPILOT_GEMINI_PRICE_OUTPUT_USD_PER_MTOK` | Standard prices from the official pricing page, above 0 and at most 1,000. |
| `DEALPILOT_GEMINI_PRICES_CHECKED_ON` | `YYYY-MM-DD` of that check, not in the future. |

Optional: `DEALPILOT_GEMINI_BASE_URL` (https only, default
`https://generativelanguage.googleapis.com/v1beta`) and the shared
`DEALPILOT_AI_TIMEOUT_SECONDS`. These settings may only **lower** the fixed maximums:

| Variable | Allowed values (default = maximum) |
|---|---|
| `DEALPILOT_AI_MAX_INPUT_CHARS` | 1 to 16,000 characters |
| `DEALPILOT_AI_MAX_OUTPUT_TOKENS` | 1 to 1,024 tokens |
| `DEALPILOT_AI_MONTHLY_BUDGET_USD` | 0 to 5.00 USD per UTC month (0 blocks every paid call) |
| `DEALPILOT_AI_MAX_CALLS_PER_HOUR` | 1 to 30 |
| `DEALPILOT_AI_USAGE_DIR` | Usage ledger folder, default `data/ai-usage`; refused if it is, is inside or contains `data/raw` or the folder named by `DEALPILOT_DATA_DIR` |

An invalid value raises `AIConfigError` naming the variable; it never falls back to a
wider value. To stop every paid call at once, set `DEALPILOT_AI_PROVIDER=mock` or
`DEALPILOT_AI_MONTHLY_BUDGET_USD=0`. Google's own prepaid balance (5 USD, automatic top-up
off) is the external cap; it can lag, so the local ledger stays mandatory.

### Usage ledger
Before each Gemini call the layer reserves its cost in the usage folder; after the call
it records the real cost from the reported usage. The reservation counts the UTF-8 bytes of
the messages as input tokens plus `max_tokens` as output tokens (D11). This is a cautious
estimate, **not a guarantee**: a call can cost more than its reservation, and the real
cost is recorded afterwards. When the outcome is uncertain (timeout, network error, a
reply without valid usage data) the reservation stays counted as spent. The ledger holds
counts and costs only, never prompts or replies. Files: `ledger-YYYY-MM.json` (one per UTC
month), `state.json` and, while a call updates them, `ledger.lock`.

Amounts are stored with 6 decimals, rounded up, so a stored reservation or cost is never
below the exact amount (at most 0.000001 USD above it).

If the ledger is unreadable or inconsistent, every Gemini call is refused with
`AIBudgetError` until a person checks and repairs it. Nothing is repaired automatically.

`state.json` lists in `months` every month that has a ledger file, plus `first_month`,
`latest_month` (the first and last of that list) and `updated_at`. Calls are refused when
a ledger file has no `state.json`, a ledger file's month is not in `months`, the current
or previous month is in `months` but its file is missing, or a time is later than now.

### Repair the usage ledger by hand
Stop every DealPilot process first, and copy the whole usage folder as a backup.
1. Delete leftover temporary files named `*.tmp-*`; they never hold committed data.
2. Each `ledger-YYYY-MM.json` must be valid JSON with `version` 1, its own `month` and an
   `entries` list. Never delete an entry to "fix" the budget: an entry you can't repair
   stays with `state` `kept`, counted at its `reserved_usd`.
3. Make `state.json` match the files: `months` = the sorted months of the
   `ledger-YYYY-MM.json` files present, `first_month` and `latest_month` = the first and
   last of them, `updated_at` = the current UTC time (ISO 8601 with `+00:00`).
4. No time in any file may be later than now. If the computer clock was wrong, wait until
   it is past those times; don't move them back.
5. Remove a stale `ledger.lock` only as described below, then run one call to check.

### A stale `ledger.lock`
The lock is held only for a moment before and after each call. If a process stops at the
wrong time, the lock stays, and every Gemini call is refused with `AIBudgetError("usage
ledger is busy")`. The lock is never removed automatically. To unblock:
1. Open `ledger.lock` in the usage folder. It holds the process id (`pid`), the computer
   (`host`), the UTC time it was created (`created_at`) and the phase (1 or 3).
2. On that computer, check that no DealPilot process with that id is still running (for
   example `Get-Process -Id <pid>` in PowerShell).
3. Only then delete `ledger.lock`.
4. A `reserved` entry left by that process keeps counting as spent. You may change its
   `state` to `kept` or `released` only after checking Google's usage page for that call.

## Errors
Every error derives from `AIError` and has `provider` and, for HTTP errors, `status`.
Messages never contain the API key, the request or the response body. Errors may also
carry an optional `reason` code (default `None`), for example the block reason of an
`AIBlockedError`; it never holds the key, the request or body text.

Limits (spec 004 amendment P4): every response body, error bodies included, is capped
at 1 MiB (`AIResponseError` above it), and `DEALPILOT_AI_TIMEOUT_SECONDS` is a total
deadline for the whole request: connect, send and every read share it, and no step
gets a fresh timeout (`AITimeoutError` when it passes). DNS lookups in the standard
library are not covered by that deadline.

| Error | Cause |
|---|---|
| `AIConfigError` | Bad or missing setting, missing or malformed key |
| `AIRequestError` | Invalid message or request |
| `AIAuthError` | HTTP 401 or 403 |
| `AIBillingError` | HTTP 402 |
| `AIRateLimitError` | HTTP 429 |
| `AIProviderError` | Other HTTP errors, network errors |
| `AITimeoutError` | Timeout |
| `AIResponseError` | Response is not valid JSON of the expected shape, or is over 1 MiB (error bodies included); for Gemini also an empty, partial or unexpected reply |
| `AIBlockedError` | Gemini blocked the content; `reason` holds the code (for example `SAFETY`) |
| `AIBudgetError` | Gemini only: monthly budget or hourly limit reached, usage ledger busy, unreadable or not writable |

For Gemini, HTTP 404 raises `AIConfigError` ("model not found"); 3xx, 400, 416, 499, 5xx
and other statuses raise `AIProviderError`. In a 2xx reply, invalid usage counts are
checked first: they raise `AIResponseError` even when the content was also blocked.

The Gemini provider is language-neutral: it adds no language instruction. DealPilot is
English-only (`AGENTS.md`); each feature that uses the layer sets the output language
(spec 005 D6).

## Switch or add a provider
Business code depends only on `get_provider`, the request and result types and the error
classes. To switch providers, change `DEALPILOT_AI_PROVIDER`. To add one:
1. Write a subclass of `dealpilot.ai.AIProvider` with a `name` and `complete()`.
2. Add it to `REGISTRY` in `dealpilot/ai/factory.py` and its name to `PROVIDERS` in
   `dealpilot/ai/config.py`.
3. Add tests with a fake transport, so no test makes a real call.
Any new provider that needs a new dependency or setting needs a spec update first.

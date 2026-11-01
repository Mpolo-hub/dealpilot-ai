# Spec 005: AI sales metrics explanation and business summary

Status: Draft (2026-10-30, revised 2026-10-31). Not approved. Nothing in this spec may be
implemented until the user approves it. Only D6 (English only, 2026-10-31) is approved;
that does not approve the spec. Limited exception (2026-10-31, `AGENTS.md`): part of D6
is implemented in `dealpilot.insights.language`: the English-only instruction, the local
language check, and the rejection of non-English or uncertain AI explanations, whose
result is returned to the caller. **Not implemented:** the fallback to the fixed English
`summary`, the number validation, and the sales-summary workflow itself. AC-SUM-11 to
AC-SUM-14 are tested only for the language rules, with a stand-in summary.
Owner: DealPilot AI team
Depends on: spec 002 (sales metrics contract, section 5.4), spec 004 (AI provider layer),
`AGENTS.md` (LLM features are optional add-ons; the MVP works without them)

## 1. Problem and goal
`/v1/sales/metrics` returns exact numbers, but a manager still has to read tables to see
what matters: which category leads, how concentrated sales are, whether the latest period
went up or down. Goal: turn one sales metrics result into a short, correct business
summary in plain language, so a user gets the main points in a few seconds.

Business objective: faster weekly and monthly sales reviews, with numbers that can be
trusted because they come from the metrics, never from the model's own guesses.

## 2. Users and usage scenario
- **Users:** sales managers and analysts of the DealPilot demo (synthetic data only).
- **Scenario:** the user picks a date range, an optional grouping (`date` with an
  interval, `product`, `category` or `region`) and optional filters, exactly as for
  `/v1/sales/metrics`. The feature computes the metrics, then returns a summary such as:
  "From 2025-01-01 to 2025-01-31: 7,935 units and 2,026,466.37 revenue from 2,354 orders.
  Outdoor leads revenue with 47.7%. Office is lowest with 3.7%."

## 3. Non-goals
- No forecasting, no advice on prices or promotions, no causes ("sales rose because...").
- No new HTTP endpoint in this spec, and no change to spec 002 (section 9).
- No chat, no free-text questions from the user, no memory between calls.
- No new dependency. No real Meta call in tests.

## 4. Inputs
The only input is one sales metrics result with the exact shape of spec 002 section 5.4
(`start`, `end`, `group_by`, `interval`, `filters`, `metrics`, `rows`, `totals`,
`row_count`), computed in-process with `dealpilot.analytics.sales.sales_metrics` and the
same validation as `/v1/sales/metrics`. No other data is read: no `expected_demand`, no
`metadata.json` `parameters`, no customers, no `list_price`, no `size_weight`.

## 5. Output
A result object:

| Field | Content |
|---|---|
| `facts` | List of deterministic facts computed in Python from the input (section 6) |
| `summary` | Plain-language English summary built from `facts` by a fixed template. Always present. |
| `ai_explanation` | Text from the AI provider, or `null` |
| `ai_status` | `ok`, `rejected` (failed validation, section 7), `error` (provider error) |
| `provider`, `model` | From the provider settings (spec 004) |

`summary` alone is a complete answer. `ai_explanation` is an optional rewording.

## 6. Facts (deterministic, provider-independent)
Computed with `Decimal` for revenue and integers for counts, never from the model:
1. Range, filters and totals (units, revenue, orders, order lines).
2. With one non-date grouping: the top and bottom group by revenue and by units, each with
   its share of the total in percent, rounded half-up to 1 decimal.
3. With `group_by=date`: the first and last buckets and the change between them in units
   and revenue, in percent (rounded half-up to 1 decimal), or "not defined" when the first
   bucket is 0. Missing buckets count as 0 (spec 002 D5).
4. With several groupings, or more than 20 rows: only facts 1 and 2 for the first grouping,
   computed over all rows, and the note that the result was summarized.
5. With no rows (no sales): totals only, and the fact "no sales in this range".

## 7. AI explanation
- **Prompt:** a fixed system message, then one user message holding the facts as a JSON
  block. The prompt says to use only the given numbers. At most 20 facts, so the prompt
  stays small.
- **Validation:** every number in the AI text (digits with optional separators, decimals
  or `%`) must equal a number in `facts` once separators are removed. Otherwise the text is
  dropped and `ai_status` is `rejected`. The text must also be at most 1,200 characters.
- **Language (D6).** Every AI explanation is in English, whatever the language of the
  input data (for example product or region names). The fixed system message includes
  this instruction:
  "Respond in English only. Use clear, professional business English. Preserve all
  supplied figures, names, dates, categories and business meaning exactly. Do not
  translate, recalculate, invent or modify numerical results."
  The user message starts with a fixed English sentence before the JSON block, so the
  mock reply, which repeats it, passes the language check. The instruction belongs to
  this feature; the providers stay language-neutral (spec 006 section 10).
- **Language check (D6).** After the number check, a local heuristic with the standard
  library only (no new dependency) decides whether the AI text is clearly English:
  1. Words are the letter sequences of the text, lowercased. Words that appear in the
     facts (product, category and region names, filters, dates) and every number are
     ignored, so names, companies and figures never count. English indicators (rule 2)
     always count, even when they also appear in the facts.
  2. English indicators are common English function words (for example "the", "and",
     "of", "with", "from", "was"). French and Portuguese indicators are common words
     of those languages that are not English (for example "les", "des", "une",
     "avec", "pour", "dans", "est", "ventes", "não", "uma", "com", "vendas"),
     plus French or Portuguese accented letters in the remaining words. Accents alone
     never decide: all accented words together count as one indicator at most.
  3. Accepted only when clearly English: at least 3 English indicators and no French or
     Portuguese indicator.
  4. Clearly non-English (at least 2 French or Portuguese indicators, or more of them
     than English ones) or uncertain (any other case): the text is dropped, `ai_status`
     is `rejected`, and the English `summary` is returned with `facts` unchanged.
  5. The AI text is never translated or edited, and the check never changes `facts`,
     `summary`, figures or the business meaning.
  Limits: this is a heuristic, not a language identification. It can reject a correct
  English text (for example a very short one); that is the safe side. It can accept
  a language it has no indicators for. The word lists live in the code and are tested.
- **Mock provider (spec 004):** the default. Its reply is deterministic and repeats the
  prompt, so it passes validation and the whole path runs offline with no key.
- **Meta provider:** used only when `DEALPILOT_AI_PROVIDER=meta` (spec 004 D3). Nothing
  in the business logic changes.
- **Provider independence:** the feature calls only `get_provider()`,
  `CompletionRequest`, `Message` and the `AIError` classes from `dealpilot.ai`.

## 8. Errors and fallback
- Invalid query input: the same errors as `/v1/sales/metrics` (spec 002 section 3.5),
  raised before any AI call.
- Missing data: the spec 002 `DataUnavailable` error, before any AI call.
- Any `AIError` (config, auth, billing, rate limit, timeout, invalid response): no
  exception reaches the user; `ai_explanation` is `null`, `ai_status` is `error`, and
  `summary` is still returned. The error class name is kept for logs; its message is not
  shown.
- The feature never retries.

## 9. API implications
None in this spec. Serving the summary over HTTP needs (a) an approved update to spec 002,
whose section 2 says "no Meta or other LLM APIs", and (b) a decision on the path and error
codes. Until then the feature is a Python function only (Q1).

## 10. Privacy and security
- Only aggregated sales numbers, dates, product, category and region IDs and names from the
  synthetic dataset go into the prompt. No customer data, no hidden generator parameters.
- Product and category names are data inside the JSON block, never instructions.
- The API key stays in the spec 004 `Secret`; nothing here logs or returns it.
- With the default mock provider no data leaves the machine.

## 11. Acceptance criteria (proposed)
Tests in `backend/tests/test_summary_*.py`, named `test_ac_sum_NN_...`, on hand-made
metrics results and fake providers. No network.

| ID | Criterion |
|---|---|
| AC-SUM-01 | Facts 1 to 3 match hand-computed values for a category grouping and a monthly date grouping, including half-up percent rounding. |
| AC-SUM-02 | An empty result gives totals and "no sales in this range"; a first date bucket of 0 gives "not defined" for the change. |
| AC-SUM-03 | More than 20 rows or several groupings follow fact 4. |
| AC-SUM-04 | `summary` is identical for the same input, with any provider and any provider outcome. |
| AC-SUM-05 | With the mock provider and no key, `ai_status` is `ok` and the result is deterministic. |
| AC-SUM-06 | A fake provider reply with a number not in `facts` gives `ai_status` `rejected` and `ai_explanation` `null`; a reply over 1,200 characters does too. |
| AC-SUM-07 | Each `AIError` subclass raised by a fake provider gives `ai_status` `error`, the summary, and no exception. |
| AC-SUM-08 | The prompt holds no field outside section 4's allowed list; a product name with instruction-like text stays inside the JSON block. |
| AC-SUM-09 | Invalid input raises the spec 002 error before any provider call (the fake provider records zero calls). |
| AC-SUM-10 | No route is added to the API app. |
| AC-SUM-11 | The system message holds the D6 instruction word for word, and the user message starts with the fixed English sentence, for any input data. |
| AC-SUM-12 | A fake provider reply in French or in Portuguese gives `ai_status` `rejected`, `ai_explanation` `null`, and `facts` and the English `summary` identical to those of an accepted reply. |
| AC-SUM-13 | An uncertain reply (for example fewer than 3 English indicators, or one French or Portuguese indicator among English words) gives `ai_status` `rejected` and the English `summary`. |
| AC-SUM-14 | An English reply that uses names from the facts with accents or non-English words (for example a product named "Café Crème" or a region named "São Paulo") and figures from the facts gives `ai_status` `ok`. |

## 12. Testing strategy
Unit tests on hand-made metrics dictionaries, a fake provider that records calls and
returns fixed text or raises, and the real `MockProvider`. No generator run is needed;
one optional integration test may use the session `default_run` fixture (temporary
folder), never `data/raw`.

## 13. Dependencies
None new. Uses `dealpilot.analytics` (spec 002) and `dealpilot.ai` (spec 004).

## 14. Decisions needing approval
| ID | Proposed decision | State |
|---|---|---|
| D1 | The feature is a library function in a new `dealpilot.insights` module; no endpoint. | Proposed |
| D2 | Numbers come only from deterministic facts; the AI text is optional and validated. | Proposed |
| D3 | AI failures never fail the feature; the template summary is always returned. | Proposed |
| D4 | Limits: 20 rows summarized in detail, 20 facts in the prompt, 1,200 characters of AI text. | Proposed |
| D5 | Percent rounding half-up to 1 decimal, computed with `Decimal`. | Proposed |
| D6 | English only (answers Q2): every summary and AI explanation is in English whatever the input language; the fixed system message holds the English-only instruction of section 7; a local heuristic language check rejects clearly non-English or uncertain AI text, which falls back to the English `summary` with `ai_status` `rejected`; no translation, no change to figures or meaning; no new dependency. | Approved 2026-10-31 by the user's explicit decision |

## 15. Open questions
| ID | Question |
|---|---|
| Q1 | Should the summary be served over HTTP? If so, which path, and approve a spec 002 update. |
| Q2 | Should the summary be in English only, or also French? Answered by D6 (2026-10-31): English only. |
| Q3 | Is a small CLI (`python -m dealpilot.insights.summary`) wanted for local use? |
| Q4 | Which facts matter most to users beyond section 6 (for example average order value)? Adding any needs a spec update. |
| Q5 | Spec 004 Q1 (Meta wire format) must be closed before the Meta provider is used here. |

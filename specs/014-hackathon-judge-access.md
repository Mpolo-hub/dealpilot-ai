# Spec 014: Hackathon Judge Access and Authentication

Status: Approved (2026-11-03, revision 4.3). Approved in full by the product owner on
2026-11-03, together with amendments A2-H1 (spec 002) and A7-H1 (spec 007) (decision
S1-D03, including S1-D08, S1-D13 and S1-D15) and the AC-S1 acceptance criteria (S1-D11).
The Stage 1 code is authorized (2026-11-03). Deployment is **not** authorized yet.

- The spec 002 and spec 007 amendments approved with this spec are reproduced in Annex A.
  Specs 002 and 007 themselves are not edited (they are frozen references); Annex A is
  the approved text of the amendments.
- This is a hackathon demo spec, **not** a commercial SaaS spec. Specs 008 to 013 are
  unrelated and unchanged.
- It creates no user account, password, organization, role, membership, tenant or
  subscription, and no personal data.
- It exists because spec 007 section 11 (l.409) says "any use beyond one local machine
  needs an authentication spec first".

## A. Confirmed product owner decisions (APPROVED BY PRODUCT OWNER, recorded 2026-11-03)

| ID | Decision |
|---|---|
| S1-D02 | Number and title: **spec 014, "Hackathon Judge Access and Authentication"** (the number and title only; the content stays Draft) |
| S1-D04 | Official hackathon end **2026-11-04**; demo period 30 calendar days; **shutdown date 2026-12-04**; the app must deny access after the approved deadline |
| S1-D05 | Invitations are **reusable** until expiry or explicit revocation; expired and revoked invitations are rejected; revocation prevents further use; no single use; session security not weakened |
| S1-D17 | Architecture **AR-2**: a **SQLite** database on a **1 GB persistent volume** for invitations, expiry and revocation, server-side sessions, session invalidation and persistent rate-limit records. AR-1 rejected; AR-2b and AR-3 not selected. Fly.io preferred, subject to the hosting approval (S1-D09) |

## B. Parameters confirmed by the product owner (2026-11-03)

Each parameter below was **explicitly confirmed by the product owner** as an individual
decision (later, the whole spec was approved: see the Status line). It is
not an authorization to write application code or to deploy. Every related acceptance test
stays mandatory, and none is passed until it is run with evidence.

| Ref | Parameter | Value | Decision | Status |
|---|---|---|---|---|
| P-1 | Invitation life | **7 days** from issue, never past `demo_end` | S1-D05a | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-2 | Session inactivity timeout | **60 minutes** | S1-D06 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-3 | Absolute session life | **8 hours** from redemption, never past the invitation's `not_after` or `demo_end` | S1-D06 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-4 | Rate limiting | Persistent (SQLite), by client identity and by invitation; values in JA-SR-04; subject to all six product owner conditions | S1-D07 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-5 | SQLite durability | WAL with `synchronous=FULL` | JA-Q8 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-6 | Process user | Non-root app user; folder 0700, file 0600 | JA-Q9 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-7 | Restore policy | **Option 1: NEVER restore the SQLite access database.** If it becomes unusable, initialize a fresh database (`init`) and issue new invitations. No restoration workflow exists (section 13) | JA-Q10 | CONFIRMED BY PRODUCT OWNER (2026-11-03) |
| P-8 | Shutdown time | **2026-12-04 23:59:59 Africa/Luanda (UTC+01:00)**, configured as `2026-12-04T23:59:59+01:00` (= `2026-12-04T22:59:59Z`) | S1-D04a | CONFIRMED BY PRODUCT OWNER (2026-11-03) |

**The product owner's six conditions on P-4 (confirmed together with P-4), and where each is
specified (specified, not yet verified or tested):**
1. No raw IP in SQLite: JA-SR-04.
2. A keyed HMAC identity: JA-SR-04.
3. The HMAC secret is kept outside the database: JA-SR-04 and JA-FR-02.
4. A retention and cleanup policy: JA-SR-08.
5. The proposed limits are kept: JA-SR-04, unchanged.
6. The trusted client IP behind Fly.io: section 10, "Client IP".

**Note on P-8:**
- Africa/Luanda is West Africa Time, UTC+01:00, with no daylight saving time.
- **Recommendation:** store the deadline with its fixed offset (`+01:00`) rather than the
  zone name, so the check needs no time-zone database at runtime.
- The **date** 2026-12-04 is approved (S1-D04); the **time and zone** are confirmed (P-8,
  S1-D04a).

## 1. Goal

Let a small number of invited hackathon judges and demonstrators use the existing
read-only RC1 application (Dashboard, Sales analysis, Products, Data; synthetic seed 42
data) over the internet until the shutdown deadline. Everyone else gets no data and no
API.

## 2. Non-goals

- Accounts, sign-up, passwords, email, an identity provider, MFA.
- Organizations, roles, permissions beyond "has a valid session".
- Any write to business data. The only writes are to the access store.
- Gemini and forecasting: their access rules are added when those stages are approved.
- Collecting names, emails or raw IP addresses.

## 3. Concepts

- **Access store:** one SQLite file on the persistent volume, at `DEALPILOT_DEMO_STORE`.
  - It is separate from the analytics: DuckDB and the seed 42 Parquet files are not
    touched, migrated or moved (section 10).
  - It is outside `DEALPILOT_DATA_DIR`.
  - Its tables:
    - `meta(schema_version)`;
    - `invitations(invite_id, label, token_hash, not_after, revoked_at, created_at)`;
    - `sessions(session_hash, invite_id, created_at, last_seen, absolute_expiry)`;
    - `rate_counters(scope, subject_key, window_start, count)`. The scope is one of
      `redeem_ip`, `redeem_invite`, `api_ip` and `api_invite`.
- **Invite token:** 32 random bytes (`secrets.token_urlsafe`). Only its SHA-256 hash is
  stored.
- **Invite link:** `https://<demo-host>/access#<token>`. The token is in the URL fragment,
  so browsers do not send it to servers in the request line or the Referer.
- **Session ID:** 32 random bytes in the cookie. Only its SHA-256 hash is stored.
- **Client key:** `HMAC-SHA256(DEALPILOT_DEMO_HASH_KEY, normalized client IP)`.
  - Normalization: an IPv4 address as is; an **IPv6 address reduced to its /64 prefix**,
    so one client cannot evade the limit by rotating addresses inside its own /64.
  - The raw IP is never stored or logged.
  - The key is a host secret, never in the database or the repository.
- **`demo_end`:** from `DEALPILOT_DEMO_END`, an ISO 8601 time with offset (P-8).
- **Admin command:** a local command run on the host:
  - `init` (creates the store; the app never does);
  - `create --label judge-01` (prints the link once);
  - `list`;
  - `revoke <invite_id|label>`;
  - `revoke-all`.

  **There is no admin HTTP endpoint.**

## 4. Requirements

### Invitations
- **JA-FR-01. Generation.** `create` makes a random token, stores its hash with a
  non-personal `label` and `not_after`, and prints the link once. The token is never
  stored or printed again. `not_after` = the issue time + the invitation life (P-1: 7
  days), capped at `demo_end`.
- **JA-FR-02. Configuration.** These come from the process environment (host secrets or
  variables):
  - `DEALPILOT_DEMO_MODE=public`;
  - `DEALPILOT_DEMO_STORE`;
  - `DEALPILOT_DEMO_END`;
  - `DEALPILOT_DEMO_HASH_KEY` (at least 32 random bytes). It is held only as a host
    secret, **never written to the SQLite store**. Rotating it resets the IP counters only;
    sessions and invitations are not affected;

  There is no `.env` file and no secret in the repository. In public mode, the app stops
  at start-up (fail closed) if:
  - the store file is missing;
  - it is unwritable;
  - it is inside the data folder;
  - it fails its integrity or schema check;
  - `DEALPILOT_DEMO_END` is missing or has no offset;
  - the hash key is missing or too short.
- **JA-FR-03. Revocation (immediate).** `revoke` sets `revoked_at` and deletes every
  session of that invitation, in one transaction. The next request from those sessions
  gets 401. `revoke-all` does the same for every invitation. No restart is needed.
- **JA-FR-04. Reuse (S1-D05, APPROVED).** An invitation may be redeemed several times, on
  any device, until `not_after`, `revoked_at` or `demo_end`. Each redemption is logged
  with its `label`. A token whose hash is unknown, or whose invitation is revoked or
  expired, or a time past `demo_end`, is refused.

### Redemption and sessions
- **JA-FR-05. Redemption.**
  1. The `/access` page reads the fragment token.
  2. It posts the token in a JSON body to `POST /access/redeem` (at most 1 KB).
  3. It removes the fragment from the address bar at once.
  4. On success, the server creates a session row and sets the cookie.
  5. On failure, it shows one generic message: "This link is not valid or has expired."
     It never says why.
- **JA-FR-06. Session cookie.**
  - Name: `__Host-dealpilot-demo`.
  - Value: the random session ID only.
  - Attributes: `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain`.
- **JA-FR-07. Expiry.**
  - Idle expiry: P-2, 60 minutes.
  - Absolute expiry: P-3, 8 hours.
  - Neither may go past `not_after` or `demo_end`.

  Every protected request looks up the session, checks its expiry and its invitation's
  state, and updates `last_seen` (at most once per minute). An expired row is deleted and
  the request gets 401.
- **JA-FR-08. Logout.** `POST /access/logout` deletes the session row and clears the
  cookie. A copy of the cookie is then useless.

### Protection
- **JA-FR-09. Protected routes.** Every `/v1` path (and any later Gemini or forecast
  route) needs a valid session. Otherwise: 401, with the spec 002 error body and code
  `unauthorized`.
- **JA-FR-10. Public routes.** Only these are public:
  - `GET /health`, which touches neither the store nor the data;
  - `GET /access` and the static frontend assets;
  - `POST /access/redeem`;
  - `POST /access/logout`.

  `/docs`, `/redoc` and `/openapi.json` are not served in public mode.
- **JA-FR-11. Shutdown enforcement, on every protected request.**
  - **Deadline:** P-8, 2026-12-04 23:59:59 Africa/Luanda = `2026-12-04T22:59:59Z`.
  - **Checks:** the check is the **first step** of the access check on:
    - every protected request;
    - `POST /access/redeem`;
    - the admin command `create`, which refuses to create an invitation past the deadline.

    The check runs **before** any store lookup, so it holds even if the store is
    unreadable.
  - **Clock:** the comparison uses the current UTC time against the configured time with
    its offset. No time-zone database is needed.
  - **After the deadline:** every request gets 401. The static assets and the access page
    may still load, but no data and no API.
- **JA-SR-01. CSRF.** Both POST routes require:
  - `Content-Type: application/json`;
  - an `Origin` header equal to the demo origin;
  - for logout, the `SameSite=Strict` cookie.

  Anything else gets 403.
- **JA-SR-02. Token hygiene.** Tokens and session IDs are stored only as SHA-256 hashes.
  They never appear in logs, errors or responses (except the one `Set-Cookie`), or in the
  frontend bundle.
- **JA-SR-03. Transport.** HTTPS only, with HSTS. The cookie is `Secure`.
- **JA-SR-04. Persistent rate limits** (P-4; the values are part of S1-D07, PROPOSED).
  All counters are stored in `rate_counters` in fixed windows, written inside the same
  `BEGIN IMMEDIATE` transaction as the check, so **they survive restarts**.

  | Scope | Key | Proposed limit |
  |---|---|---|
  | `redeem_ip` | client key | 5 per minute, 30 per hour |
  | `redeem_invite` | `invite_id` (only after the token hash matches) | 20 per hour |
  | `api_ip` | client key | 240 per minute |
  | `api_invite` | `invite_id` of the session | 120 per minute (all sessions of one invitation together) |

  - **Identity** (P-4 conditions 1 to 3): the `redeem_ip` and `api_ip` keys are the
    client key of section 3: an HMAC with a host-secret key over the normalized IP. The
    raw IP never reaches SQLite or the logs. The `invite` keys are the non-secret
    `invite_id`.
  - **Source of the IP** (P-4 condition 6): section 10, "Client IP".
  - The limits are those proposed in revision 4, unchanged (P-4 condition 5). They will be
    revised only if staging measurements show a problem, by a new product owner decision.
  - Over a limit: 429 with code `rate_limited` (the spec 002 body on `/v1`).
  - **Write cost:** section 10, "Write contention".
- **JA-SR-05. Logging.** Redemptions, refusals, logouts, revocations, 401 and 429 are
  logged with:
  - the time;
  - the event;
  - the invitation `label` (when known);
  - the path;
  - the status.

  No token, session ID, cookie, raw IP or secret is logged.
- **JA-SR-06. Data minimization.** No name, email, phone or account is stored. Labels must
  not be personal.
- **JA-SR-08. Retention and cleanup** (P-4 condition 4).

  | Data | Kept | Removed |
  |---|---|---|
  | `rate_counters` rows | Until the end of their window | Windows older than 1 hour (the longest window) are deleted inside the next write transaction, at most once a minute |
  | `sessions` rows | Until idle or absolute expiry, logout or revocation | Deleted when found expired, at logout or revocation, and by the same periodic cleanup |
  | `invitations` rows (including expired and revoked ones) | Until shutdown, so a revoked or expired invitation stays refused | Deleted with the volume at shutdown |
  | App logs (no raw IP, token or session ID) | The host's log retention | Deleted with the app at shutdown |
  | `DEALPILOT_DEMO_HASH_KEY` and the other host secrets | The demo period | Deleted at shutdown |
  | Volume snapshots | Fly retention (5 days by default) | Section 9, snapshot clean-up |

- **JA-SR-07. Store integrity.** One app process on one machine; WAL mode;
  `synchronous=FULL` (P-5); transactions on every write; a non-root owner with 0700 and
  0600 modes (P-6).

## 5. User-visible text

English only (AGENTS.md; spec 007 section 8). All strings are in `frontend/src/text/en.ts`
(AC-UI-11):
- the access page: "Opening the DealPilot AI demo...";
- the generic failure message;
- the signed-out page: "Your demo session has ended. Open your invitation link again, or
  ask the organizer for a new one.";
- the sign-out button;
- the rate-limit message: "Too many requests, try again in a minute."

## 6. Acceptance criteria

The full list is in Annex B: AC-S1-AUTH-01 to 15,
AC-S1-STORE-01 to 09, AC-S1-RL-01 and 02. Under P-4, AC-S1-RL-01 also covers the
per-invitation limits and their survival across a restart.

## 7. Open questions

| ID | Question | Status |
|---|---|---|
| JA-Q1 | Reuse | **ANSWERED** (S1-D05) |
| JA-Q2 | Session times | **ANSWERED:** P-2 60 minutes, P-3 8 hours (CONFIRMED BY PRODUCT OWNER (2026-11-03)) |
| JA-Q3 | Rate-limit values and identity | **ANSWERED:** P-4 with its six conditions (CONFIRMED BY PRODUCT OWNER (2026-11-03)). The write cost is not measured yet (AC-S1-PERF-01) |
| JA-Q4 | Invitation life | **ANSWERED:** P-1 7 days (CONFIRMED BY PRODUCT OWNER (2026-11-03)) |
| JA-Q5 | Spec number | **ANSWERED:** 014 (S1-D02) |
| JA-Q6 | Shutdown | **ANSWERED:** 2026-12-04 23:59:59 Africa/Luanda, UTC+1 (S1-D04 and P-8, CONFIRMED BY PRODUCT OWNER (2026-11-03)) |
| JA-Q7 | Architecture | **ANSWERED:** AR-2 (S1-D17) |
| JA-Q8 | SQLite `synchronous` | **ANSWERED:** WAL with FULL (P-5, CONFIRMED BY PRODUCT OWNER (2026-11-03)) |
| JA-Q9 | Non-root user and volume ownership | **ANSWERED:** P-6 (CONFIRMED BY PRODUCT OWNER (2026-11-03)); the ownership mechanics on Fly.io are still to verify on staging (technical test) |
| JA-Q10 | Restore policy | **ANSWERED:** Option 1, never restore the access database (P-7, CONFIRMED BY PRODUCT OWNER (2026-11-03)) |
| JA-Q11 | Content approval of spec 014 (Draft to Approved) | **ANSWERED:** Approved 2026-11-03 (revision 4.3) |
| JA-Q12 | Client IP source: `Fly-Client-IP`, **not trusted until the mandatory pre-production spoofing test passes** (section 10) | PENDING (technical check) |
| JA-Q13 | Snapshot clean-up | **ANSWERED:** turn off automatic snapshots on 2026-11-29 (CONFIRMED BY PRODUCT OWNER (2026-11-03)). Existing snapshots are not deleted by this; no deletion is promised for 2026-12-04; the final inventory and post-expiry check stay mandatory |

## 8. Dependencies

- No new package: the Python standard library `sqlite3`, `hashlib`, `hmac` and `secrets`,
  plus FastAPI and Starlette, which already exist.
- SQLite as the demo-only access store (S1-D17, APPROVED). After spec 014 is approved,
  AGENTS.md "Stack" should mention it (amendments draft, section 5). AGENTS.md is not
  changed now.
- The spec 002 and spec 007 amendments (S1-D03, PENDING).
- An approved host with one persistent volume (S1-D09, PENDING).

## 9. Expiry, shutdown and cleanup

- **Shutdown:** 2026-12-04 (S1-D04, APPROVED). Proposed time: 23:59:59 Africa/Luanda,
  which is `2026-12-04T23:59:59+01:00` (P-8, PENDING).
- **Invitations:** expire at `not_after` (P-1: 7 days), capped at `demo_end`.
- **Sessions:** expire per P-2 and P-3.
- **The app** refuses all access from `demo_end` on (JA-FR-11).
- **Snapshot clean-up.** These facts were verified on https://docs.fly.io/volumes/snapshots
  on 2026-11-03:
  - [F] Snapshots are kept for the retention period (5 days by default; 1 to 60 days can
    be set).
  - [F] "Disabling automatic snapshots will not remove any existing snapshots".
  - [F] A changed retention "won't affect existing snapshots".
  - [F] The page documents no command to delete a single snapshot.
  - [F] It says data can be restored "from a deleted volume", so **snapshots can outlive
    the volume**.
  - [A] Whether deleting the whole Fly app deletes its snapshots is **not verified**.

  **Confirmed by the product owner (JA-Q13, 2026-11-03):**
  1. On **2026-11-29**, turn off automatic snapshots
     (`fly volumes update <id> --scheduled-snapshots=false`). **This does not delete
     existing snapshots** ([F] above). They stay until their own retention ends, which is
     about 5 days after each one was taken. **No deletion is promised for 2026-12-04.**
  2. **Mandatory after shutdown:** a final snapshot inventory
     (`fly volumes snapshots list <id>`, for every volume the app has had). For
     each snapshot, record its creation time and expected expiry. Check again after the
     last expiry, and record that none remains, or what remains and why.

  Any snapshot that remains holds only hashes, non-personal labels and times. It holds no
  token, raw IP or personal data. **Snapshots are never used to restore the access database
  (P-7).**
- **Shutdown procedure, by the product owner, on or right after the deadline:**
  1. `revoke-all` (the app already refuses everything after the deadline).
  2. Stop the app.
  3. Delete the app, image, volume (with the access store) and logs at the host.
  4. Make the final snapshot inventory above (mandatory), and repeat it after the last
     expected expiry.
  5. Delete the host secrets and variables, including `DEALPILOT_DEMO_HASH_KEY`.
  6. Delete any DNS record.
  7. Record the shutdown, with the time.
- **Cleanup:** no personal data exists (labels, hashes and times only). The synthetic data
  can be regenerated. The product owner owns the account, card, secrets and deletion.

## 10. SQLite design and reliability

**Legend:**
- **[F]** verified fact, with its source;
- **[R]** recommendation;
- **[A]** assumption to verify.

**Nothing is implemented.**

**Separation from the analytics:**
- [F] The analytics open an in-memory DuckDB connection per request (`analytics/dataset.py`
  l.112; `forecasting/inputs.py` l.125) over read-only Parquet files. No DuckDB file is
  persisted.
- [R] The SQLite store is a separate file in a separate folder. The analytics never open
  it, and the access code never opens DuckDB or the Parquet files. Nothing is migrated.

**Runtime facts:**
- [F] Python 3.13.17 with SQLite 3.50.4, `threadsafety == 3` (checked in `backend/.venv`,
  2026-11-03).
- [F] The `/v1` handlers are plain `def` (`api/v1.py` l.51, l.67, l.104), so they run in a
  thread pool. The start command has no `--workers` (`api/main.py` l.3-4).
- [R] One uvicorn process on one machine.

**Connections and transactions:**
- [R] One short-lived connection per request, not shared across threads, with:
  - `journal_mode=WAL`;
  - `synchronous=FULL` (P-5);
  - `foreign_keys=ON`;
  - `busy_timeout=5000`.
- [R] Every write runs in `BEGIN IMMEDIATE ... COMMIT`.
- [R] A revoke and its session deletions run in one transaction.
- [R] The admin command uses the same pragmas. WAL serves one writer and many readers on a
  local disk; [F] the Fly volume is local to its host.

**Fail-closed rules:**
- [R] The app never creates the database; only `init` does. A missing file at start-up
  means the app refuses to start.
- [R] `PRAGMA quick_check` and the schema-version check run at start-up. On failure, the
  app refuses to start.
- [R] Any SQLite error on a protected request gives 503 with the generic message and no
  data. An error never grants access.

**Permissions (P-6):**
- [R] A non-root app user; the folder is 0700 and the file 0600.
- [A] How the Fly volume mount is owned, and how the image sets ownership, is to be
  verified on staging.

**Client IP behind the Fly.io proxy** (P-4 condition 6). **An unverified header is never
treated as a trusted client identity.**
- [F] Fly docs (https://docs.fly.io/networking/request-headers, read 2026-11-03):
  - `Fly-Client-IP` is "The IP address of the client from the perspective of Fly Proxy";
  - if no other proxy is in front, it "might be a better choice to get client IP
    addresses";
  - `X-Forwarded-For` "must be treated with caution to avoid spoofing attempts";
  - the page does **not** say whether Fly's proxy overwrites a `Fly-Client-IP` header sent
    by the client.
- **Required TLS and HTTP proxy configuration** ([R]; the exact `fly.toml` keys are to be
  checked against Fly's configuration docs before use, [A]):
  - **One** HTTP service only, with TLS ended at the Fly proxy (HTTP and TLS handlers),
    `force_https` on, and the app listening on its internal port.
  - **No** other service or port is exposed: no raw TCP service and no extra public
    ports.
  - **No** Flycast or private service address is allocated to the app, and no other app
    shares its organization's private network. Fly's private network and WireGuard peers
    can reach a machine directly, without the proxy, and those requests carry no
    `Fly-Client-IP` ([A], to verify).
  - **No** other proxy or CDN is placed in front. That would change what `Fly-Client-IP`
    means ([F] above).
- **Application rules** ([R]):
  - In public mode, a request that does **not** carry exactly one well-formed
    `Fly-Client-IP` value is refused with 403 and no data. This closes any path that
    bypasses the Fly proxy.
  - Never use `request.client.host` (that is the proxy). Do not enable uvicorn's generic
    proxy-header trust.
  - **Until the spoofing test passes, the IP-based limits are treated as unverified.**
    They are not counted as a security control in the go-live gate. Only the
    per-invitation limits, which do not depend on the IP, count.
- **Mandatory pre-production spoofing test** (AC-S1-RL-05). Send requests through the
  public URL with a forged `Fly-Client-IP` and a forged `X-Forwarded-For`, and confirm the
  app sees the real client address.
  - **If Fly does not overwrite the forged header,** `Fly-Client-IP` must **not** be used.
    The fallback (the address Fly's proxy appends to `X-Forwarded-For`, parsed from the
    right as the Fly page advises) must pass the same test before the IP limits count.
- **Direct-access test** (AC-S1-DEP-04): a request that reaches the machine without
  passing the Fly proxy (for example from the private network) is refused with 403.

**Write contention with `synchronous=FULL`** (P-5 and P-4):
- [F] SQLite with WAL allows one writer at a time; other writers wait up to `busy_timeout`
  (5,000 ms recommended).
- **Writes per request** ([R]):
  - Each protected request runs **one** short `BEGIN IMMEDIATE` transaction: the session
    check, the shutdown check, two counter upserts (`api_ip` and
    `api_invite`), and `last_seen` at most once a minute. That is one WAL commit and one
    durable sync.
  - A redemption adds a few rows in one transaction.
- **Expected load:** the RC1 Dashboard issues about 6 parallel `/v1` calls per page view
  (spec 007 section 5.1). With a few judges, that is at most tens of transactions per
  second at peaks.
- [A] **This is an estimate only. Nothing has been measured.** A WAL commit with a full
  sync on a local NVMe disk usually takes milliseconds. The shared CPU and the real disk
  may differ.
- **Proposed acceptance criterion** (AC-S1-PERF-01; **a proposal, not a result**):
  - 10 concurrent `/v1` requests add at most 100 ms at the 95th percentile, compared with
    the store disabled;
  - no `SQLITE_BUSY` error after the timeout.

  **It must be measured by an actual test on staging with SQLite in WAL mode and
  `synchronous=FULL`, on the chosen machine size and volume.**
- **If it fails:** this is technical evidence for a new product owner decision (P-4
  condition 5). Options:
  - write `last_seen` less often;
  - merge the counter rows;
  - as a last resort, change P-5.

  Nothing is changed silently.

**Restarts and deploys:**
- [F] Fly docs: with one Machine and a volume, "you'll have downtime ... whenever you deploy
  your app".
- [R] Deploy outside the judges' viewing windows. WAL recovery restores the last committed
  state.

## 11. Failure scenarios

| Scenario | Expected behavior ([R] unless marked) | Residual risk |
|---|---|---|
| Machine restart | The store is reopened and checked; sessions, revocations and **all rate counters** persist (P-4) | None significant |
| Volume unavailable | The file is missing, so the app refuses to start | Downtime |
| Host hardware failure | [F] "that instance of your app goes down". Recovery (P-7): a new machine and volume, a fresh `init`, new invitations. **No snapshot restore** | Downtime; new links |
| Database corruption | `quick_check` fails, so the app refuses to start; a runtime error gives 503. Recovery: `init` and re-issue | Downtime; new links |
| Disk full | Writes fail, so requests are denied (503); never opened | Very low (1 GB for a few hundred rows) |
| Concurrent redemptions of one invitation | Each gets its own session in its own transaction; the per-invitation counter is updated atomically | None beyond reuse |
| Revocation during an active session | The sessions are deleted in the revoke transaction; the next request gets 401. A request already past its check may finish | Very low |
| Restore of a snapshot | **Not allowed (P-7, Option 1).** The runbook has no restore step. A restored copy could bring back revoked access (section 13), which is why it is forbidden | Operator error only; covered by the runbook and AC-S1-STORE-14 |

## 13. No-restoration policy (P-7, CONFIRMED BY PRODUCT OWNER, 2026-11-03)

**Policy: the SQLite access database is NEVER restored** from a snapshot or any other
copy. If it becomes unusable (corruption, volume loss, host failure, failed integrity
check), the product owner:
1. creates a fresh database with `init` (on the existing volume, or a new one);
2. issues new invitations;
3. records the event.

Every earlier link and cookie is then refused, because the new database does not contain
them.

**Why** (analysis kept as the reason for the policy):
- [F] A restore creates a new volume from a snapshot, holding the state at snapshot time
  (https://docs.fly.io/volumes/snapshots).
- Invitations revoked, or sessions ended, after the snapshot would be valid again inside
  the copy. The app cannot tell a restored copy from the original.
- Never restoring removes this risk entirely.

**Consequences:**
- **No restoration workflow is specified or to be implemented.** The earlier alternative
  (maintenance mode, the external cutoff `DEALPILOT_DEMO_NOT_BEFORE`, controlled restore)
  is **not adopted** and is removed from this spec.
- Snapshots exist only until automatic snapshots are turned off on 2026-11-29 (JA-Q13).
  They are never used for recovery. The final inventory and post-expiry check stay
  mandatory (section 9).
- The operations runbook must contain the policy, and no restore command.

**Verification:** the policy is shown only when these tests pass:
- AC-S1-STORE-13 (fresh-init recovery refuses all earlier links and cookies);
- AC-S1-STORE-14 (the runbook has no restore step).

## 14. Revision history

- **Revision 1:** stateless (AR-1).
- **Revision 2:** a persistent store, after the product owner's security review.
- **Revision 3:** spec number 014 approved (S1-D02); AR-2 approved (S1-D17); SQLite
  reliability and failure scenarios added.
- **Revision 4 (2026-11-03):** the proposed parameters P-1 to P-8 were added in section B:
  - a 7-day invitation life;
  - a 60-minute idle and 8-hour absolute session;
  - persistent rate limits by IP and invitation;
  - `synchronous=FULL`;
  - a non-root owner;
  - daily snapshots with `revoke-all` after restore;
  - a shutdown at 2026-12-04 23:59:59 Africa/Luanda.

  The `/v1` rate limits moved from in-memory to persistent. The confirmed decisions are
  separated from the proposals. **The spec is not Approved.**
- **Revision 4.1 (2026-11-03):** P-1 to P-8 were wrongly marked "approved in principle"
  (corrected in 4.2). Added:
  - the P-4 conditions: HMAC identity with IPv6 /64 normalization; the key kept outside the
    database; JA-SR-08 retention; the client IP from `Fly-Client-IP`, with a mandatory
    staging check against forgery;
  - write-contention analysis and an acceptance threshold;
  - the shutdown check as the first step of every protected request;
  - section 13 on restore safety, with the external fence `DEALPILOT_DEMO_NOT_BEFORE` and
    maintenance mode;
  - snapshot clean-up from 2026-11-29.

  The spec stays Draft.
- **Revision 4.2 (2026-11-03), corrections requested by the product owner:**
  - P-1 to P-8 set to "RECOMMENDED - AWAITING EXPLICIT PRODUCT OWNER CONFIRMATION";
  - the cutoff `DEALPILOT_DEMO_NOT_BEFORE` protects only if updated at every restoration;
    Option 1 (never restore) is preferred; Option 2 is a controlled procedure; the
    protection is not complete until its tests pass;
  - the Fly.io proxy configuration and the direct-access refusal are required; an
    unverified `Fly-Client-IP` is not trusted;
  - the 2026-11-29 snapshot shutdown is a proposal; existing snapshots are not deleted by
    it; no deletion is promised on 2026-12-04; a final inventory is required;
  - the 100 ms p95 criterion is a proposal, to be measured with WAL and
    `synchronous=FULL`.

  **The spec stays DRAFT - NOT APPROVED.**
- **Revision 4.3 (2026-11-03):** the product owner confirmed, as individual decisions:
  - P-1 to P-6;
  - P-7, Option 1: never restore;
  - P-8;
  - JA-Q13.

  The restore alternative, the cutoff `DEALPILOT_DEMO_NOT_BEFORE` and maintenance mode were
  removed. Section 13 is now the no-restoration policy. All acceptance tests stay mandatory
  and unexecuted. **The spec stays DRAFT - NOT APPROVED.** It is not an authorization to
  code or deploy.
- **Approval (2026-11-03):** the product owner approved revision 4.3 in full, with
  A2-H1, A7-H1 (S1-D03) and AC-S1 (S1-D11), and authorized the Stage 1 code. The earlier
  history lines saying "DRAFT - NOT APPROVED" describe the state before this approval.

## Annex A. Approved amendments A2-H1 (spec 002) and A7-H1 (spec 007)

Approved by the product owner on 2026-11-03 (S1-D03). Text as approved:

**Approved 2026-11-03 (S1-D03 / S1-D11).**

Status: 2026-11-03, scratchpad only. These are proposed amendment texts for product owner
review. **The repository specs are not changed.** Each amendment needs the product
owner's explicit approval before any code. Approved decision tables are not rewritten:
new rows are added (AGENTS.md, How we work 2).

Stage 1 uses only existing behavior plus the judge-access spec. **Gemini and forecasting
are not amended here.** Specs 003, 005 and 006 stay as they are for Stage 1.

## 1. Spec 002 (HTTP API v1), amendment A2-H1 "Stage 1 public demo mode"

**Why:**
- Section 2 (l.36): "No authentication, users or rate limits. The API is for local use
  only."
- Section 3.5 (l.104-108) keeps FastAPI defaults outside `/v1`.
- Main docstring: `/docs` is served.

**Proposed text** (new section 2.1 and new decision rows):
- **Public demo mode.** When `DEALPILOT_DEMO_MODE=public`, the app runs as the Stage 1
  hackathon demo until `DEALPILOT_DEMO_END`. In this mode only:
  - **Access.** Every `/v1` path needs a valid judge-access session (judge-access spec
    JA-FR-09). Without one: 401, with the section 3.5 body and the new code
    `unauthorized`.
  - **Rate limits.** Over the judge-access limits: 429, with code `rate_limited`.
  - **Docs.** `/docs`, `/redoc` and `/openapi.json` are not served (404).
  - **Static frontend.** Paths outside `/v1`, `/health` and `/access/*` serve the built
    frontend (`frontend/dist`); unknown non-API paths return `index.html` (SPA fallback).
    `/v1` 404, 405 and 422 behavior is unchanged.
  - **Headers.** Every response carries the security headers of the spec 007 amendment
    A7-H1.
  - Everything else in v1 is unchanged: routes, parameters, validation order and
    response bodies.
- **Local mode** (default, no variable set): exactly today's behavior, including
  `/docs`. RC1 local use is unchanged.
- **Status table (section 3.5):** add 401 "No valid demo session (public demo mode only)",
  403 "Request refused by the CSRF check (access routes only)" and 429 "Rate limit
  reached".
- **New decision rows:**
  - D-H1 "Public demo mode as above, approved ____";
  - D-H2 "Static frontend served outside `/v1` in public demo mode only; this replaces D13
    for that mode only".
- **Acceptance:** AC-API-18 to 22, which are AC-S1-API-01 to 05 in the acceptance file.

## 2. Spec 007 (web frontend), amendment A7-H1 "Stage 1 public demo"

**Why:**
- D1 (l.731): "neither the app nor the API may be exposed publicly".
- Section 11 (l.406-409): "any use beyond one local machine needs an authentication spec
  first".
- RC1 approval (l.7-9): it excludes public or cloud deployment.
- D9: `vite preview` is for local use only.
- Section 3.2: no user menu.
- Section 11 CSP as a meta tag (`frame-ancestors` is ignored there, release-candidate
  l.74).

**Proposed text** (new decision rows; D1 is kept as it stands):
- **D1-H1.** Exception to D1 for the Stage 1 hackathon demo only:
  - the four RC1 screens may be served publicly over HTTPS, behind the judge-access spec,
    on synthetic seed 42 data only;
  - from approval until `demo_end` (the official hackathon end date + 30 days);
  - local use stays the default.
- **D9-H1.** In public demo mode, the backend serves `frontend/dist` on the same origin
  (spec 002 D-H2). `vite dev` and `vite preview` are never public. There are still no
  CORS headers.
- **D15-H1, new screens** (minimum, with no menu entry, so D6 is unchanged):
  - **S1-a, access page** (`/access`): reads the fragment token, posts it, cleans the
    URL, shows the generic failure message.
  - **S1-b, signed-out page:** shown on 401 from any `/v1` call, on expiry and after
    sign-out.
  - **S1-c, sign-out button** in the top bar. This is a single control, not a user menu.
  - **S1-d, demo notice.** A permanent line in the shell: "Hackathon demo. Synthetic data
    (seed 42). Not a commercial product." This supports the "no commercial SaaS claims"
    direction.

  All strings go in `text/en.ts` (AC-UI-11). Every screen has the section 5 states, plus
  the 401 and 429 handling: a 401 on any card shows S1-b; a 429 shows "Too many requests,
  try again in a minute" in the card.
- **Section 11-H1, security in public demo mode.** HTTP response headers set by the
  backend:
  - `Content-Security-Policy` with today's directives, including `frame-ancestors 'none'`;
  - `Strict-Transport-Security: max-age=31536000`;
  - `X-Content-Type-Options: nosniff`;
  - `Referrer-Policy: no-referrer`;
  - `Cache-Control: no-store` on `/v1` and `/access/*`.

  The existing rules stay: no secrets in the frontend, no external resources, no AI call
  from the frontend.
- **D13-H1, testing for the demo.** It depends on S1-D10:
  - either Playwright browsers are authorized for the acceptance run only;
  - or HTTP-level tests plus a recorded manual browser checklist are used.
- **Acceptance:** AC-UI-19 to 24, which are AC-S1-UI-01 to 06 in the acceptance file.

## 3. New spec 014: Hackathon Judge Access and Authentication

Its number and title were approved by the product owner on 2026-11-03 (S1-D02). Its
architecture, AR-2 with a SQLite store, was approved the same day (S1-D17). The full draft
is in `dealpilot-ai-stage1-judge-access-spec-draft.md`. Its content must be approved
before any Stage 1 code.

The spec 002 amendment A2-H1 refers to it for the 401, 429 and 503 behavior. In public
mode, a 503 is also returned when the access store fails (spec 014 section 10).

## 4. Dependency change: npm advisory (D-14)

**Why:**
- spec 007 l.696-697 and `docs/release-candidate.md` l.193-195: "Before any public
  deployment: re-run `npm audit`, and approve an ESLint and `typescript-eslint` upgrade
  that resolves it";
- AGENTS.md How we work 6: ask before changing a dependency.

**Proposed:**
- Approve upgrading the ESLint and `typescript-eslint` development dependencies to
  versions that resolve GHSA-g3hv-75wg-m249. The exact versions are to be found and shown
  to the product owner before the change.
- Re-run `npm audit` with 0 moderate or higher findings in the build chain. Lockfile only;
  no runtime dependency change.

## 5. Documents to update after approval (not now)

- `docs/roadmap.md`: AGENTS.md says to keep it current after each change. It already has
  pending, uncommitted changes, which must be preserved; any update is made in the same
  file with care.
- `docs/release-candidate.md`: a note that the public demo is a separate, time-limited
  exception.
- AGENTS.md "Stack": today it says "Storage: DuckDB + Parquet". After spec 014 is
  approved, add one line: "SQLite only as the demo access store of spec 014 (Stage 1
  hackathon demo), approved 2026-11-03 (S1-D17); never for analytics". This needs the
  product owner's approval, as a documentation change.
- AGENTS.md: optional, a one-line pointer to the demo mode.

## 6. Unchanged for Stage 1

- Specs 003, 005 and 006 (forecasting and Gemini are excluded from Stage 1).
- Specs 008 to 011 and the Draft 013 (D-20).
- U-01: not decided. The demo host is **not** a U-01 decision.
- The frozen references and P-2.

## Annex B. Approved acceptance criteria AC-S1 (S1-D11)

Approved by the product owner on 2026-11-03 (S1-D11). Text as approved:

**Approved 2026-11-03 (S1-D03 / S1-D11).**

Status: 2026-11-03, scratchpad only. These are proposed criteria for the Stage 1 public
demo: the RC1 screens behind judge access, synthetic seed 42, no Gemini, no forecasting.
They become binding only when the product owner approves them (S1-D11).

Tests are named after the criterion ID (AGENTS.md How we work 3). "E" marks a criterion
already met by existing tests or code; "N" marks new work. "Where" says how each runs:
- **unit:** pytest with the FastAPI TestClient, or Vitest;
- **staging:** HTTP checks against the deployed staging URL (a scripted client);
- **manual:** a recorded browser checklist, unless S1-D10 authorizes Playwright.

## Authentication and authorization (judge-access spec)

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-AUTH-01 | Given a valid invitation, when its link is opened, then the token is posted to `/access/redeem`, the fragment is removed from the URL, the `__Host-dealpilot-demo` cookie is set with `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, and `/` loads | N | unit + manual |
| AC-S1-AUTH-02 | Given a token with a bad HMAC, an unknown or revoked `invite_id`, a past `not_after`, or a time after `demo_end`, when it is redeemed, then the response refuses it with one generic message and sets no cookie; the message is identical for all causes | N | unit |
| AC-S1-AUTH-03 | Reuse (S1-D05, Option B, approved): redemptions of the same invitation before its `not_after` succeed, and each is logged with its label. After `not_after`, after revocation, or after `demo_end`, redemption is refused | N | unit (clock injected) |
| AC-S1-AUTH-04 | Given a session idle past the idle limit, or past the absolute limit, when it calls `/v1/metadata`, then 401 `unauthorized` | N | unit (clock injected) |
| AC-S1-AUTH-05 | When `POST /access/logout` is called, then the session row is deleted and the cookie cleared; **a copy of the same cookie value, sent afterwards from another client, gets 401** | N | unit |
| AC-S1-AUTH-06 | When the admin command revokes an invitation, then, **with no restart**, its link is refused and every one of its sessions gets 401 on the next request | N | unit |
| AC-S1-AUTH-07 | `revoke-all` refuses every link and ends every session at once | N | unit |
| AC-S1-AUTH-08 | In public mode, a missing or unwritable access store, a store inside the data folder, or a missing or invalid `DEALPILOT_DEMO_END` stops the app at start-up | N | unit |
| AC-S1-AUTH-13 | **Restart persistence:** after a restart, valid sessions still work; revoked invitations and logged-out sessions stay refused; redemption-attempt counters keep their values within their window | N | unit (store reopened) |
| AC-S1-AUTH-14 | The store holds only hashes of tokens and session IDs (no raw token or ID); there is no admin HTTP route (any `/admin` path is 404) | N | unit + review |
| AC-S1-AUTH-15 | The cookie value is only the random session ID (no readable claims) | N | unit |
| AC-S1-STORE-01 | In public mode, if the SQLite file does not exist (for example, the volume is not mounted), the app refuses to start and **does not create it**; only the admin `init` command creates it | N | unit |
| AC-S1-STORE-02 | If `PRAGMA quick_check` fails, or the schema version is wrong, at start-up, the app refuses to start | N | unit (corrupted fixture file) |
| AC-S1-STORE-03 | Any SQLite error during a protected request (forced disk-full, corruption or busy timeout through a test double) gives 503 with the generic message and **no data**; never 200 | N | unit |
| AC-S1-STORE-04 | Concurrent redemptions of one invitation (parallel threads) each create a valid session; the store stays consistent (`quick_check` ok) | N | unit |
| AC-S1-STORE-05 | A revoke committed while sessions are active: every later request of those sessions gets 401; the revoke and the session deletion are in one transaction | N | unit |
| AC-S1-STORE-06 | The store runs in WAL mode with the approved `synchronous` level; the file is 0600 and its folder 0700, owned by the app user | N | unit + staging (JA-Q9) |
| AC-S1-STORE-07 | The analytics code never opens the SQLite store, and the access code never opens DuckDB or the Parquet files; the `/v1` results are identical with and without the store present | N | unit + review |
| AC-S1-STORE-08 | **WITHDRAWN** (P-7 confirmed: never restore). No restore test exists, because no restore is allowed | n/a | n/a |
| AC-S1-STORE-09 | Exactly one machine and one uvicorn process run in the demo app (host listing reviewed) | N | staging |
| AC-S1-STORE-10 | **WITHDRAWN** (P-7: the cutoff `DEALPILOT_DEMO_NOT_BEFORE` is not adopted) | n/a | n/a |
| AC-S1-STORE-11 | **WITHDRAWN** (P-7: maintenance mode is not adopted) | n/a | n/a |
| AC-S1-STORE-12 | Retention (JA-SR-08): counter windows older than 1 hour and expired sessions are deleted by the periodic cleanup; revoked and expired invitations stay and stay refused | N | unit (clock injected) |
| AC-S1-RL-03 | No raw IP address appears in the SQLite file or in the logs after a test run (byte scan for the test IPs); the client keys change when `DEALPILOT_DEMO_HASH_KEY` changes; the key is not stored in the database | N | unit |
| AC-S1-RL-04 | Two IPv6 addresses in the same /64 share one client key; addresses in different /64s do not | N | unit |
| AC-S1-RL-05 | **Mandatory pre-production spoofing test:** requests through the public URL carrying a forged `Fly-Client-IP` and a forged `X-Forwarded-For` are counted under the real client address. Until it passes, the IP limits are not counted as a security control (JA-Q12) | N | staging (must be run) |
| AC-S1-PERF-01 | **Proposed criterion, not a measured result.** Staging test with SQLite in WAL mode and `synchronous=FULL`, on the chosen machine and volume: 10 concurrent `/v1` requests with the store active add at most 100 ms at the 95th percentile compared with the store disabled, with no `SQLITE_BUSY` after the timeout | N | staging (must be run) |
| AC-S1-OPS-05 | Shutdown deadline: one second before `2026-12-04T23:59:59+01:00` a valid session works; at the deadline every protected request, redeem and `create` is refused; the check also holds with an unreadable store | N | unit (clock injected) |
| AC-S1-OPS-06 | Final snapshot inventory (mandatory): after shutdown, `fly volumes snapshots list` for each volume is recorded with each snapshot's creation and expected expiry; it is checked again after the last expected expiry. No deletion on 2026-12-04 is assumed | N | operations record |
| AC-S1-STORE-14 | No-restoration policy: the operations runbook states "never restore the access database", contains no snapshot-restore command, and gives the fresh-init procedure (P-7) | N | review |
| AC-S1-STORE-13 | Fresh-init recovery (P-7, mandatory): after deleting or corrupting the store, `init` creates an empty store; every earlier link and cookie is refused; new invitations work | N | unit + staging |
| AC-S1-DEP-04 | A request that reaches the app without passing the Fly proxy (no `Fly-Client-IP`, or more than one value, or a malformed value) is refused with 403 and no data, in public mode; on staging, a request from the private network is refused | N | unit + staging |
| AC-S1-AUTH-09 | `POST /access/redeem` or `/access/logout` without `Content-Type: application/json`, or with an `Origin` that is not the demo origin, gets 403 and no change | N | unit |
| AC-S1-AUTH-10 | A redeem body over 1 KB gets 413 or 422 and is not processed | N | unit |
| AC-S1-AUTH-11 | No token, session ID or cookie value appears in any log line or response body (except the one `Set-Cookie`) in a full test run (log capture scan) | N | unit + staging |
| AC-S1-AUTH-12 | The access store holds only invitation IDs, non-personal labels, hashes, times and keyed-hash client keys; no email, name or raw IP is stored | N | review |

## HTTPS and security headers

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-TLS-01 | `http://` requests to the demo are redirected to `https://` or refused; the certificate is valid for the demo host | N | staging |
| AC-S1-HDR-01 | Every response has `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and a `Content-Security-Policy` HTTP header containing `default-src 'self'` and `frame-ancestors 'none'` | N | unit + staging |
| AC-S1-HDR-02 | `/v1` and `/access/*` responses have `Cache-Control: no-store` | N | unit |

## API protection and rate limiting

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-API-01 | In public mode, without a session, `GET /v1/metadata`, `/v1/dimensions` and `/v1/sales/metrics` return 401 with the spec 002 section 3.5 body and code `unauthorized`, and no data | N | unit + staging |
| AC-S1-API-02 | In public mode, `/docs`, `/redoc` and `/openapi.json` return 404 | N | unit + staging |
| AC-S1-API-03 | In local mode (no `DEALPILOT_DEMO_MODE`), behavior is exactly as today: AC-API-01 to 17 pass and `/docs` is served | E (AC-API-01 to 17) + N (mode switch) | unit |
| AC-S1-API-04 | With a session, the `/v1` contracts are unchanged: AC-API-01 to 17 pass in public mode with a session | N | unit |
| AC-S1-RL-01 | Persistent limits (spec 014 revision 4, P-4): redeem attempts over the per-IP or per-invitation limit get 429 `rate_limited`; `/v1` requests over the per-IP or per-invitation limit get 429 with the spec 002 body; **after a restart, counters within their window keep their values**; limits reset after their window | N | unit (clock injected, store reopened) |
| AC-S1-RL-02 | The client IP used for limits comes only from the configured platform header; a forged `X-Forwarded-For` does not bypass the limit | N | unit |

## Frontend and backend deployment

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-DEP-01 | In public mode, `/`, `/analysis`, `/products` and `/data` load the built frontend from the same origin; the browser makes no cross-origin request and the API sends no CORS headers | N | staging + manual |
| AC-S1-DEP-02 | An unknown non-API path returns `index.html` (SPA fallback); unknown `/v1` paths keep the spec 002 404 body | N | unit |
| AC-S1-DEP-03 | Neither `vite dev` nor `vite preview` runs on the host | N | review of the container command |
| AC-S1-UI-01 | Access page: valid link goes to the Dashboard; invalid link shows the generic message | N | Vitest + manual |
| AC-S1-UI-02 | Any 401 from a `/v1` call shows the signed-out page | N | Vitest |
| AC-S1-UI-03 | The sign-out button calls logout and shows the signed-out page | N | Vitest |
| AC-S1-UI-04 | The demo notice "Hackathon demo. Synthetic data (seed 42). Not a commercial product." is visible on every page | N | Vitest |
| AC-S1-UI-05 | A 429 in a card shows the rate-limit message; other cards keep working | N | Vitest |
| AC-S1-UI-06 | All new strings come from `text/en.ts`; AC-UI-11 (English only) still passes | E (AC-UI-11) + N | Vitest |

## Synthetic seed 42 data

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-DATA-01 | With a session, `/v1/metadata` reports `seed` 42 and the row counts of the generator's default run | E (API) | staging |
| AC-S1-DATA-02 | The image contains only the generator output for seed 42 in `DEALPILOT_DATA_DIR`; no other data file | N | review of the image build |
| AC-S1-DATA-03 | The Data page shows the dataset is synthetic | E (metadata) + N (notice) | manual |

## npm security alert

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-NPM-01 | After the approved upgrade, `npm audit` reports no moderate-or-higher advisory (GHSA-g3hv-75wg-m249 resolved); `npm test`, `npm run typecheck` and `npm run lint` pass | N | unit |

## Error handling

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-ERR-01 | Spec 002 errors keep their bodies and codes; no stack trace or internal path appears in any response in public mode | E (`/v1` errors) + N (public-mode check) | unit |
| AC-S1-ERR-02 | If the data folder is missing, `/v1` returns 503 `data_unavailable` and the UI shows the Data unavailable view (existing). In public mode the message must not reveal local paths; the current message names a local command, so the amendment must decide its public wording | E + N | unit |

## Rollback and shutdown

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-OPS-01 | Redeploying the previous image tag restores the previous version on staging | N | staging (rehearsal recorded) |
| AC-S1-OPS-02 | After `demo_end` (S1-D04, approved: 2026-12-04; time and zone S1-D04a), every redeem and `/v1` request is refused even if the app is still running; one second before it, a valid session still works | N | unit (clock injected) |
| AC-S1-OPS-03 | The shutdown procedure (judge-access spec section 9) is rehearsed once on staging: `revoke-all`, stop the app, delete the app, volume (with the access store), logs and secrets; the result is recorded | N | staging |
| AC-S1-OPS-04 | `/health` answers 200 for the platform health check without a session and without touching data | E | unit |

## Regression

| ID | Given / When / Then | E/N | Where |
|---|---|---|---|
| AC-S1-REG-01 | The backend default suite passes (`pytest`; today 980 passed, 1 skipped) and `ruff check` (with the S rules) passes | E | unit |
| AC-S1-REG-02 | The frontend suite passes (`npm test`, today 50 passed), plus `npm run typecheck` and `npm run lint` | E | unit |
| AC-S1-REG-03 | The 362-entry frozen baseline shows no new difference except the files of the approved Stage 1 change, which are listed in a new supplemental register like the P-2 one | N | integrity check |

**Status of all criteria (2026-11-03): none executed. All are mandatory and unpassed** (except the withdrawn STORE-08, 10 and 11). They become binding when the product owner approves them (S1-D11). P-1 to P-8 being confirmed does not pass any test.

## Annex C. Amendment 2026-11-03: Render free hosting (S1-D17 and S1-D09 amended)

Approved by the product owner on 2026-11-03. It changes the hosting only; every other rule
of this spec stays.

- **Host.** The Render free web service, with no persistent disk, at 0 USD. Fly.io support
  stays, and the host is selected through environment variables.
- **Client IP** (P-4 condition 6). The header is set by `DEALPILOT_DEMO_CLIENT_IP_HEADER`
  (default `Fly-Client-IP`).
  - **On Render, use `CF-Connecting-IP`.** Render's guide says Cloudflare "writes that
    header on every request that reaches a Render web service, and it overwrites whatever
    the caller sent".
  - In `X-Forwarded-For` mode, the app trusts only the entry `DEALPILOT_DEMO_XFF_HOPS`
    places from the right (default 1), because Cloudflare "appends to `X-Forwarded-For`
    rather than replacing it". The leftmost entries are controlled by the caller.
  - A request without a valid value is still refused with 403.
  - The spoofing test RL-05 is mandatory on the real host.
- **Ephemeral store** (`DEALPILOT_DEMO_EPHEMERAL_STORE=1`).
  - At start-up a missing store is created with the same schema, pragmas (WAL,
    `synchronous=FULL`) and modes (0700 and 0600), then checked with `quick_check` and the
    schema version.
  - A store that exists but fails its checks is never replaced.
  - Without this variable, the strict rule stays: the app refuses to start without the
    store.
  - The store is never restored (P-7).
- **Invitation bootstrap** (`DEALPILOT_DEMO_INVITES`, a host secret).
  - Format: entries `label|code|issued`, separated by `;` or new lines. `code` is at least
    32 URL-safe characters. `issued` is an ISO 8601 time with offset.
  - Expiry is `issued` + 7 days (P-1), capped at the shutdown deadline (P-8).
  - Only SHA-256 hashes are stored, and codes are never logged or shown in errors.
  - The secret is the source of truth at start-up: an entry removed from it is revoked, and
    its sessions are deleted. A changed code ends that label's sessions.
  - Revocation and expiry changes take effect by editing the secret and redeploying.
- **Accepted residual risks (product owner, 2026-11-03).**
  - Sessions and rate-limit counters reset on every restart or sleep.
  - A cold start after sleep can take up to about one minute.
  - Revocation needs a redeploy.

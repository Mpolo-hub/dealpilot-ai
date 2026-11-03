"""SQLite access store (spec 014 AR-2, sections 3, 4 and 10).

Every write runs in one BEGIN IMMEDIATE transaction. Tokens and session IDs are stored only
as SHA-256 hashes; client IPs only as an HMAC client key made by the caller. The app never
creates the database: only `init` (the admin command) does (fail closed).
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from dealpilot.demo.config import ABSOLUTE_SECONDS, IDLE_SECONDS

SCHEMA_VERSION = "1"
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE invitations (
    invite_id TEXT PRIMARY KEY,
    label TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE,
    not_after INTEGER NOT NULL,
    revoked_at INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE sessions (
    session_hash TEXT PRIMARY KEY,
    invite_id TEXT NOT NULL REFERENCES invitations(invite_id) ON DELETE CASCADE,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    absolute_expiry INTEGER NOT NULL
);
CREATE TABLE rate_counters (
    scope TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    window_seconds INTEGER NOT NULL,
    window_start INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (scope, subject_key, window_seconds, window_start)
);
"""
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

# Spec 014 JA-SR-04 (P-4, confirmed): (scope, window seconds, limit).
REDEEM_IP = (("redeem_ip", 60, 5), ("redeem_ip", 3600, 30))
REDEEM_INVITE = (("redeem_invite", 3600, 20),)
API_IP = (("api_ip", 60, 240),)
API_INVITE = (("api_invite", 60, 120),)
LONGEST_WINDOW = 3600
CLEANUP_EVERY = 60
LAST_SEEN_EVERY = 60


class StoreError(Exception):
    """The store is missing, unreadable or fails its checks (fail closed)."""


class RateLimited(Exception):
    """A rate limit was reached."""


@dataclass(frozen=True)
class Grant:
    session_id: str
    max_age: int
    label: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    """Open an existing store read-write; never create it."""
    if not path.is_file():
        raise StoreError("access store not found")
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=rw", uri=True,
                               isolation_level=None, timeout=5.0, check_same_thread=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        raise StoreError("access store cannot be opened") from None
    return conn


def init(path: Path, now: int) -> None:
    """Create a new, empty store (admin `init`). Refuses to overwrite an existing file."""
    if path.exists():
        raise StoreError("access store already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=rwc", uri=True, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(statement)
        conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        conn.execute("INSERT INTO meta VALUES ('last_cleanup', ?)", (str(int(now)),))
        conn.execute("COMMIT")
    finally:
        conn.close()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def check(path: Path) -> None:
    """Start-up check: the file exists, `quick_check` is ok and the schema version matches."""
    conn = connect(path)
    try:
        ok = conn.execute("PRAGMA quick_check").fetchone()
        version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    except sqlite3.Error:
        raise StoreError("access store failed its checks") from None
    finally:
        conn.close()
    if not ok or ok[0] != "ok" or not version or version[0] != SCHEMA_VERSION:
        raise StoreError("access store failed its checks")


def _hit(conn: sqlite3.Connection, limits, subject: str, now: int) -> bool:
    """Count one request in every window of `limits`; True when any limit is exceeded."""
    over = False
    for scope, window, limit in limits:
        start = now - now % window
        count = conn.execute(
            "INSERT INTO rate_counters VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT (scope, subject_key, window_seconds, window_start) "
            "DO UPDATE SET count = count + 1 RETURNING count",
            (scope, subject, window, start)).fetchone()[0]
        over = over or count > limit
    return over


def _cleanup(conn: sqlite3.Connection, now: int) -> None:
    last = conn.execute("SELECT value FROM meta WHERE key='last_cleanup'").fetchone()
    if last and now - int(last[0]) < CLEANUP_EVERY:
        return
    conn.execute("DELETE FROM rate_counters WHERE window_start + window_seconds < ?",
                 (now - LONGEST_WINDOW,))
    conn.execute("DELETE FROM sessions WHERE absolute_expiry <= ? OR last_seen + ? <= ?",
                 (now, IDLE_SECONDS, now))
    conn.execute("UPDATE meta SET value = ? WHERE key = 'last_cleanup'", (str(now),))


def create_invitation(conn: sqlite3.Connection, label: str, now: int, life: int,
                      end: int) -> tuple[str, str, int]:
    if not LABEL.fullmatch(label):
        raise ValueError("label must be 1 to 32 lowercase letters, digits or hyphens")
    if now >= end:
        raise ValueError("the demo deadline has passed")
    token = secrets.token_urlsafe(32)
    invite_id = secrets.token_urlsafe(16)
    not_after = min(now + life, end)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO invitations VALUES (?, ?, ?, ?, NULL, ?)",
                     (invite_id, label, digest(token), not_after, now))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return invite_id, token, not_after


def redeem(conn: sqlite3.Connection, token: str, client_key: str, now: int,
           end: int) -> Grant | None:
    """Exchange a token for a session. None means refused (one generic answer)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        _cleanup(conn, now)
        if _hit(conn, REDEEM_IP, client_key, now):
            conn.execute("COMMIT")
            raise RateLimited
        row = conn.execute(
            "SELECT invite_id, label, not_after, revoked_at FROM invitations WHERE token_hash=?",
            (digest(token),)).fetchone()
        if row is None or row[3] is not None or row[2] <= now or now >= end:
            conn.execute("COMMIT")
            return None
        invite_id, label, not_after, _ = row
        if _hit(conn, REDEEM_INVITE, invite_id, now):
            conn.execute("COMMIT")
            raise RateLimited
        session_id = secrets.token_urlsafe(32)
        expiry = min(now + ABSOLUTE_SECONDS, not_after, end)
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                     (digest(session_id), invite_id, now, now, expiry))
        conn.execute("COMMIT")
    except RateLimited:
        raise
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return Grant(session_id=session_id, max_age=max(expiry - now, 0), label=label)


def check_session(conn: sqlite3.Connection, session_id: str | None, client_key: str,
                  now: int, end: int) -> str | None:
    """Count the request and validate the session. Returns the label, or None (401)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _hit(conn, API_IP, client_key, now):
            conn.execute("COMMIT")
            raise RateLimited
        if not session_id:
            conn.execute("COMMIT")
            return None
        key = digest(session_id)
        row = conn.execute(
            "SELECT s.invite_id, s.last_seen, s.absolute_expiry, i.not_after, i.revoked_at, "
            "i.label FROM sessions s JOIN invitations i USING (invite_id) "
            "WHERE s.session_hash=?", (key,)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        invite_id, last_seen, expiry, not_after, revoked_at, label = row
        if (revoked_at is not None or expiry <= now or not_after <= now or now >= end
                or last_seen + IDLE_SECONDS <= now):
            conn.execute("DELETE FROM sessions WHERE session_hash=?", (key,))
            conn.execute("COMMIT")
            return None
        if _hit(conn, API_INVITE, invite_id, now):
            conn.execute("COMMIT")
            raise RateLimited
        if now - last_seen >= LAST_SEEN_EVERY:
            conn.execute("UPDATE sessions SET last_seen=? WHERE session_hash=?", (now, key))
        conn.execute("COMMIT")
    except RateLimited:
        raise
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return label


def logout(conn: sqlite3.Connection, session_id: str | None) -> None:
    if not session_id:
        return
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("DELETE FROM sessions WHERE session_hash=?", (digest(session_id),))
    conn.execute("COMMIT")


def revoke(conn: sqlite3.Connection, ident: str, now: int) -> int:
    """Revoke one invitation (by ID or label) and delete its sessions, in one transaction."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute("SELECT invite_id FROM invitations WHERE invite_id=? OR label=?",
                            (ident, ident)).fetchall()
        for (invite_id,) in rows:
            conn.execute("UPDATE invitations SET revoked_at=? WHERE invite_id=? "
                         "AND revoked_at IS NULL", (now, invite_id))
            conn.execute("DELETE FROM sessions WHERE invite_id=?", (invite_id,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def revoke_all(conn: sqlite3.Connection, now: int) -> int:
    conn.execute("BEGIN IMMEDIATE")
    try:
        count = conn.execute("UPDATE invitations SET revoked_at=? WHERE revoked_at IS NULL",
                             (now,)).rowcount
        conn.execute("DELETE FROM sessions")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return count


def sync_invitations(conn: sqlite3.Connection, invites, now: int) -> None:
    """Make the store match the DEALPILOT_DEMO_INVITES secret (the source of truth).

    Listed labels are created or updated (hash and expiry; a changed code ends that
    label's sessions). Labels no longer listed are revoked and their sessions deleted.
    Only SHA-256 hashes of the codes are stored. One transaction.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        wanted = {i.label: i for i in invites}
        rows = conn.execute("SELECT invite_id, label, token_hash FROM invitations").fetchall()
        known = {label: (invite_id, token_hash) for invite_id, label, token_hash in rows}
        for label, (invite_id, token_hash) in known.items():
            item = wanted.get(label)
            if item is None:
                conn.execute("UPDATE invitations SET revoked_at=? WHERE invite_id=? "
                             "AND revoked_at IS NULL", (now, invite_id))
                conn.execute("DELETE FROM sessions WHERE invite_id=?", (invite_id,))
                continue
            new_hash = digest(item.code)
            if new_hash != token_hash:
                conn.execute("DELETE FROM sessions WHERE invite_id=?", (invite_id,))
            conn.execute("UPDATE invitations SET token_hash=?, not_after=?, revoked_at=NULL "
                         "WHERE invite_id=?", (new_hash, item.not_after, invite_id))
        for label, item in wanted.items():
            if label not in known:
                conn.execute("INSERT INTO invitations VALUES (?, ?, ?, ?, NULL, ?)",
                             (secrets.token_urlsafe(16), label, digest(item.code),
                              item.not_after, now))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def list_invitations(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute("SELECT label, invite_id, not_after, revoked_at, created_at "
                        "FROM invitations ORDER BY created_at").fetchall()

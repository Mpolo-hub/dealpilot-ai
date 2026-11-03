"""Admin command for the demo access store (spec 014 section 3). Run on the host only.

    python -m dealpilot.demo.admin init
    python -m dealpilot.demo.admin create --label judge-01
    python -m dealpilot.demo.admin list
    python -m dealpilot.demo.admin revoke <invite_id|label>
    python -m dealpilot.demo.admin revoke-all

It reads DEALPILOT_DEMO_STORE, DEALPILOT_DEMO_END and DEALPILOT_DEMO_ORIGIN from the
environment. There is no admin HTTP route. The access database is never restored (P-7):
if it is unusable, delete it, run `init` and issue new invitations.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from dealpilot.demo import store
from dealpilot.demo.config import (
    END_VAR,
    INVITATION_LIFE_SECONDS,
    ORIGIN_VAR,
    STORE_VAR,
    DemoConfigError,
    parse_deadline,
)


def _iso(ts: int | None) -> str:
    return "-" if ts is None else datetime.fromtimestamp(ts, UTC).isoformat()


def main(argv: list[str] | None = None, env=os.environ) -> int:
    parser = argparse.ArgumentParser(prog="dealpilot.demo.admin")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    create = sub.add_parser("create")
    create.add_argument("--label", required=True)
    sub.add_parser("list")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("ident")
    sub.add_parser("revoke-all")
    args = parser.parse_args(argv)

    if not env.get(STORE_VAR):
        print(f"{STORE_VAR} is not set", file=sys.stderr)
        return 2
    path = Path(env[STORE_VAR])
    now = int(time.time())
    try:
        if args.command == "init":
            store.init(path, now)
            print("access store created")
            return 0
        store.check(path)
        conn = store.connect(path)
        try:
            if args.command == "create":
                end = parse_deadline(env.get(END_VAR, ""))
                origin = env.get(ORIGIN_VAR, "").rstrip("/")
                if not origin:
                    print(f"{ORIGIN_VAR} is not set", file=sys.stderr)
                    return 2
                invite_id, token, not_after = store.create_invitation(
                    conn, args.label, now, INVITATION_LIFE_SECONDS, end)
                print(f"invitation {invite_id} label={args.label} valid until {_iso(not_after)}")
                print(f"link (shown once): {origin}/access#{token}")
            elif args.command == "list":
                for label, invite_id, not_after, revoked_at, created_at in \
                        store.list_invitations(conn):
                    print(f"{label} {invite_id} created={_iso(created_at)} "
                          f"not_after={_iso(not_after)} revoked={_iso(revoked_at)}")
            elif args.command == "revoke":
                print(f"revoked {store.revoke(conn, args.ident, now)} invitation(s)")
            elif args.command == "revoke-all":
                print(f"revoked {store.revoke_all(conn, now)} invitation(s)")
        finally:
            conn.close()
    except (store.StoreError, DemoConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

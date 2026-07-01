# ============================================================================
# File:          manage_users.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 07:45 EST
# Author:        Claude (Anthropic) + Raghu
# Version:       1.0.0
# Purpose:       CLI to manage dashboard login users. Prompts for the password
#                locally (getpass), hashes it, and writes the gitignored user
#                store. Passwords are never echoed, logged, or committed.
#                `print-env` emits the DASHBOARD_USERS_JSON blob to paste into
#                Railway (hashes only -- no plaintext).
# Last Modified: 2026-07-01 07:45 EST
# Change Log:
#   2026-07-01 07:45 EST  v1.0.0  Initial (Claude + Raghu).
# ============================================================================
"""Add / set-password / list / remove dashboard users, or print the Railway env blob.

Usage (run from nt-bridge-v2/):
    python scripts/manage_users.py set raghu   --name "Raghu"
    python scripts/manage_users.py set vara    --name "Vara"
    python scripts/manage_users.py set dhanu   --name "Dhanu"
    python scripts/manage_users.py list
    python scripts/manage_users.py remove someone
    python scripts/manage_users.py print-env          # -> DASHBOARD_USERS_JSON=... for Railway

`set` creates the user if missing or updates the password if it exists.
Default store: .local_state/dashboard_users.json  (override with --file).
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nt_schwab_bridge.auth import UserStore, hash_password  # noqa: E402

DEFAULT_FILE = ".local_state/dashboard_users.json"


def _prompt_password() -> str:
    while True:
        pw1 = getpass.getpass("New password: ")
        if len(pw1) < 8:
            print("  Password must be at least 8 characters. Try again.")
            continue
        pw2 = getpass.getpass("Confirm password: ")
        if pw1 != pw2:
            print("  Passwords did not match. Try again.")
            continue
        return pw1


def cmd_set(store: UserStore, args: argparse.Namespace) -> int:
    username = args.username.strip().lower()
    existing = store.get(username)
    display = args.name or (existing or {}).get("display_name") or username
    print(f"{'Updating' if existing else 'Creating'} user '{username}' (display: {display}).")
    password = _prompt_password()
    store.upsert(username, hash_password(password), display_name=display)
    print(f"Saved. Store: {store.path}")
    return 0


def cmd_list(store: UserStore, _args: argparse.Namespace) -> int:
    names = store.usernames()
    if not names:
        print("(no users yet)")
        return 0
    print(f"{len(names)} user(s) in {store.path}:")
    for name in names:
        print(f"  - {name}  ({store.display_name(name)})")
    return 0


def cmd_remove(store: UserStore, args: argparse.Namespace) -> int:
    if store.remove(args.username):
        print(f"Removed '{args.username.strip().lower()}'.")
        return 0
    print(f"User '{args.username}' not found.")
    return 1


def cmd_print_env(store: UserStore, _args: argparse.Namespace) -> int:
    # Emit the exact value to paste into the Railway DASHBOARD_USERS_JSON variable.
    # Contains password HASHES only -- no plaintext.
    if store.path is None or not store.path.exists():
        print("(no user store yet -- run `set` first)", file=sys.stderr)
        return 1
    data = json.loads(store.path.read_text(encoding="utf-8"))
    blob = json.dumps(data, separators=(",", ":"), sort_keys=True)
    print(blob)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage dashboard login users.")
    parser.add_argument("--file", default=DEFAULT_FILE, help=f"user store path (default {DEFAULT_FILE})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="create a user or change a password")
    p_set.add_argument("username")
    p_set.add_argument("--name", default="", help="display name")
    p_set.set_defaults(func=cmd_set)

    p_list = sub.add_parser("list", help="list users")
    p_list.set_defaults(func=cmd_list)

    p_rm = sub.add_parser("remove", help="remove a user")
    p_rm.add_argument("username")
    p_rm.set_defaults(func=cmd_remove)

    p_env = sub.add_parser("print-env", help="print DASHBOARD_USERS_JSON blob for Railway")
    p_env.set_defaults(func=cmd_print_env)

    args = parser.parse_args(argv)
    store = UserStore(args.file)
    return args.func(store, args)


if __name__ == "__main__":
    raise SystemExit(main())

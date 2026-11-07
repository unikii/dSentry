#!/usr/bin/env python3
"""Local user management for single-instance dSentry (direct SQLite).

No new HTTP surface: run with shell access to the host.

Usage (via wrapper from repo root):
    ./scripts/users.sh list
    ./scripts/users.sh create alice
    ./scripts/users.sh set-password alice
    ./scripts/users.sh enable alice | disable alice
    ./scripts/users.sh clear-password admin   # private mode only

Or inside the API container / local venv:
    python manage_users.py list
    docker compose exec api python /hub/manage_users.py list

Notes:
- SQLITE_PATH (and .env) is respected via app.config.settings.
- Passwords use the same Argon2 hash as the API. Missing --password
  prompts securely via getpass (nothing lands in shell history).
- set-password / create revoke all existing sessions of that user.
- public mode is OAuth-only: password sign-in is disabled, so create and
  set-password are refused there. list/enable/disable still work.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys
from pathlib import Path

from app.config import settings
from app.services.auth import hash_password
from app.utils import normalize_username


def _connect() -> sqlite3.Connection:
    db_path = Path(settings.sqlite_path)
    if not db_path.exists():
        sys.exit(
            f"SQLite DB not found at {db_path} — start the API once "
            "so the schema is created, then re-run."
        )
    con = sqlite3.connect(str(db_path), timeout=30.0)
    con.row_factory = sqlite3.Row
    try:
        con.execute("SELECT id FROM users LIMIT 1")
    except sqlite3.OperationalError:
        con.close()
        sys.exit(f"No users table in {db_path} — start the API once first.")
    return con


def _get_user(con: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM users WHERE username = ?", (username,)
    ).fetchone()


def _prompt_password(confirm: bool = True) -> str:
    pw = getpass.getpass("Password: ")
    if confirm:
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2:
            sys.exit("Passwords do not match.")
    return pw


def _resolve_password(args_password: str | None) -> str:
    if args_password is not None:
        print("warning: --password exposes the secret in shell history; prefer the prompt.", file=sys.stderr)
        return args_password
    if not sys.stdin.isatty():
        sys.exit("No TTY — pass --password for non-interactive use.")
    return _prompt_password()


def cmd_list(_args: argparse.Namespace) -> int:
    con = _connect()
    rows = con.execute(
        "SELECT id, username, oauth_provider, status, "
        "CASE WHEN password_hash IS NULL THEN 0 ELSE 1 END AS has_pw, "
        "reg_at FROM users ORDER BY id"
    ).fetchall()
    con.close()
    if not rows:
        print("(no users)")
        return 0
    print(f"{'id':>4}  {'username':<24} {'oauth':<10} {'status':<8} {'pw':<3} reg_at")
    for r in rows:
        status = "active" if r["status"] == 0 else f"disabled({r['status']})"
        print(f"{r['id']:>4}  {str(r['username']):<24} {str(r['oauth_provider'] or '-'): <10} {status:<8} {'yes' if r['has_pw'] else 'no':<3} {r['reg_at']}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    if settings.run_mode != "private":
        sys.exit(
            "public mode is OAuth-only: accounts are created on first OAuth "
            "sign-in and password sign-in is disabled"
        )
    try:
        username = normalize_username(args.username)
    except ValueError:
        sys.exit("invalid username")
    if args.no_password:
        password = None
    elif args.password is not None or sys.stdin.isatty():
        # Private mode prompts when interactive.
        password = _resolve_password(args.password)
    else:
        sys.exit("refusing passwordless create non-interactively (pass --no-password to confirm)")
    if password is not None and len(password) < 6:
        sys.exit("password must be at least 6 characters")

    con = _connect()
    if _get_user(con, username) is not None:
        con.close()
        sys.exit(f"user {username!r} already exists")
    pw_hash = hash_password(password) if password else None
    try:
        cur = con.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash),
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        con.close()
        sys.exit(f"create failed: {e}")
    uid = cur.lastrowid
    con.close()
    print(f"created user {username!r} (id={uid})" + (" with no password" if pw_hash is None else ""))
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    if settings.run_mode != "private":
        sys.exit(
            "set-password is private-mode only: public mode is OAuth-only "
            "and rejects password sign-in"
        )
    try:
        username = normalize_username(args.username)
    except ValueError:
        sys.exit(f"user {args.username!r} not found")
    con = _connect()
    row = _get_user(con, username)
    if row is None:
        con.close()
        sys.exit(f"user {username!r} not found")
    if row["oauth_provider"] and not args.force:
        print(f"note: {username!r} is OAuth-linked ({row['oauth_provider']}); adding a local password too.", file=sys.stderr)
    password = _resolve_password(args.password)
    if len(password) < 6:
        con.close()
        sys.exit("password must be at least 6 characters")
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), row["id"]),
        )
        con.execute(
            "UPDATE sessions SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
            (row["id"],),
        )
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise
    con.close()
    print(f"password updated for {username!r}; all sessions revoked")
    return 0


def cmd_clear_password(args: argparse.Namespace) -> int:
    if settings.run_mode != "private":
        sys.exit("clear-password is private-mode only (public rejects passwordless login)")
    try:
        username = normalize_username(args.username)
    except ValueError:
        sys.exit(f"user {args.username!r} not found")
    con = _connect()
    row = _get_user(con, username)
    if row is None:
        con.close()
        sys.exit(f"user {username!r} not found")
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("UPDATE users SET password_hash = NULL WHERE id = ?", (row["id"],))
        con.execute(
            "UPDATE sessions SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
            (row["id"],),
        )
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise
    con.close()
    print(f"password cleared for {username!r} (passwordless login); sessions revoked")
    return 0


def _set_status(username: str, status: int) -> int:
    try:
        username = normalize_username(username)
    except ValueError:
        sys.exit(f"user {username!r} not found")
    con = _connect()
    row = _get_user(con, username)
    if row is None:
        con.close()
        sys.exit(f"user {username!r} not found")
    con.execute("UPDATE users SET status = ? WHERE id = ?", (status, row["id"]))
    if status != 0:
        con.execute(
            "UPDATE sessions SET revoked_at = datetime('now') WHERE user_id = ? AND revoked_at IS NULL",
            (row["id"],),
        )
    con.commit()
    con.close()
    print(f"user {username!r} {'enabled' if status == 0 else 'disabled'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Manage dSentry local users (direct SQLite).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="List users")
    pl.set_defaults(func=cmd_list)

    pc = sub.add_parser("create", help="Create a local user (private mode only)")
    pc.add_argument("username")
    pc.add_argument("--password", default=None, help="Password (prompt if omitted and interactive)")
    pc.add_argument("--no-password", action="store_true", help="Create without password (private mode only)")
    pc.set_defaults(func=cmd_create)

    pp = sub.add_parser(
        "set-password",
        help="Set/reset a user's password (private mode only; revokes sessions)",
    )
    pp.add_argument("username")
    pp.add_argument("--password", default=None)
    pp.add_argument("--force", action="store_true", help="Allow for OAuth-linked accounts without extra prompt")
    pp.set_defaults(func=cmd_set_password)

    cp = sub.add_parser("clear-password", help="Remove password (private mode only)")
    cp.add_argument("username")
    cp.set_defaults(func=cmd_clear_password)

    for name, st in (("enable", 0), ("disable", 1)):
        ps = sub.add_parser(name, help=f"{name} a user")
        ps.add_argument("username")
        ps.set_defaults(func=(lambda _a, st=st: _set_status(_a.username, st)))

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "list":
        return cmd_list(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

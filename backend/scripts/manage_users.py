"""Manage sign-in identities in MongoDB (Feature 15).

    python scripts/manage_users.py set-password --email admin1@campusride.demo
        password from $CAMPUSRIDE_PASSWORD, else a hidden prompt (never a CLI argument)
    python scripts/manage_users.py set-demo-passwords
        every seeded user gets $DEMO_USER_PASSWORD (local AUTH_MODE=password demos only)
    python scripts/manage_users.py disable --email driver05@campusride.demo
    python scripts/manage_users.py enable  --email driver05@campusride.demo

Re-seeding (scripts/seed_db.py) replaces users, so set passwords again afterwards.
Passwords are stored only as scrypt hashes; nothing secret is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.db import Database, redact_uri
from app.core.passwords import hash_password
from app.repositories.mongo import mongo_repositories


def _password_from_env_or_prompt(var: str) -> str:
    pw = os.environ.get(var)
    if pw:
        return pw
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("passwords do not match")
    return first


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(settings.mongo_uri, settings.mongo_db)
    try:
        if not await database.ping():
            print(f"MongoDB not reachable at {redact_uri(settings.mongo_uri)}")
            return 2
        users = mongo_repositories(database.db).users
        now = datetime.now(UTC)
        if args.command == "set-demo-passwords":
            pw = os.environ.get("DEMO_USER_PASSWORD")
            if not pw:
                print("set DEMO_USER_PASSWORD in the environment first")
                return 1
            all_users = await users.list(limit=1_000_000)
            digest = hash_password(pw)  # one hash: same demo password everywhere (dev only)
            for u in all_users:
                await users.upsert(u.model_copy(update={"password_hash": digest, "updated_at": now}))
            print(f"set the demo password for {len(all_users)} users")
            return 0
        user = await users.by_email(args.email)
        if user is None:
            print(f"no user with email {args.email}")
            return 1
        if args.command == "set-password":
            update = {"password_hash": hash_password(_password_from_env_or_prompt("CAMPUSRIDE_PASSWORD"))}
        else:
            update = {"active": args.command == "enable"}
        await users.upsert(user.model_copy(update={**update, "updated_at": now}))
        print(f"{args.command}: {user.email} ({user.role.value}, {user.id})")
        return 0
    finally:
        database.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("set-password", "disable", "enable"):
        sub.add_parser(name).add_argument("--email", required=True)
    sub.add_parser("set-demo-passwords")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())

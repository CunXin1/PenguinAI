#!/usr/bin/env python3
"""Grandfather existing accounts past the hard email-verification gate.

Hard verification (see CLAUDE.md → Registration Flow) blocks any account whose
``email_verified`` is false from logging in or holding a usable token. Accounts
created before that gate landed have ``email_verified=false`` and would suddenly
be locked out. This one-off marks every currently-unverified user as verified.

It does NOT change behaviour for new sign-ups: they still register as unverified
and must confirm their email. Run this once, after deploying the gate.

RUN (from repo root, with .env present and Postgres reachable):
    python3 scripts/verify_existing_users.py            # apply
    python3 scripts/verify_existing_users.py --dry-run  # count only, no writes
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verify_existing_users")


async def run(dry_run: bool) -> None:
    from backend.app.core.config import settings

    engine = create_async_engine(settings.DATABASE_URL)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        pending = (
            await db.execute(text("SELECT count(*) FROM users WHERE email_verified = false"))
        ).scalar_one()

        if pending == 0:
            logger.info("No unverified accounts — nothing to do.")
            await engine.dispose()
            return

        if dry_run:
            logger.info("[dry-run] would mark %d existing account(s) as verified.", pending)
            await engine.dispose()
            return

        result = await db.execute(
            text("UPDATE users SET email_verified = true WHERE email_verified = false")
        )
        await db.commit()
        logger.info("Marked %d existing account(s) as verified.", result.rowcount)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="count unverified accounts without writing"
    )
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))

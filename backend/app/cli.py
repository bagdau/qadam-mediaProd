"""Operations CLI: ``python -m app.cli <command>``."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import Crypto, DecryptionError, generate_key
from app.db.session import dispose_engine, get_sessionmaker
from app.models import ConnectedAccount, Publication, UserRole
from app.services import auth as auth_service


async def create_user(args: argparse.Namespace) -> int:
    password = args.password or os.environ.get("QADAM_PASSWORD") or getpass.getpass("Password: ")
    async with get_sessionmaker()() as db:
        user = await auth_service.create_user(
            db, args.email, password, display_name=args.name or "", role=UserRole.ADMIN if args.admin else UserRole.MEMBER
        )
    print(f"created user {user.email} ({user.role})")
    return 0


async def rotate_encryption(_: argparse.Namespace) -> int:
    """Re-encrypt every stored secret with the primary key (first entry of ENCRYPTION_KEYS)."""
    crypto = Crypto(get_settings().encryption_key_list)
    rotated = 0
    async with get_sessionmaker()() as db:
        for account in (await db.execute(select(ConnectedAccount))).scalars():
            for attr in ("access_token_enc", "refresh_token_enc"):
                value = getattr(account, attr)
                if value:
                    setattr(account, attr, crypto.rotate(value))
                    rotated += 1
        for pub in (await db.execute(select(Publication).where(Publication.upload_url_enc.is_not(None)))).scalars():
            pub.upload_url_enc = crypto.rotate(pub.upload_url_enc)
            rotated += 1
        await db.commit()
    print(f"re-encrypted {rotated} values")
    return 0


async def migrate_sqlite(args: argparse.Namespace) -> int:
    from app.legacy_migration import LegacyMigrationError, import_legacy

    crypto = Crypto(get_settings().encryption_key_list)
    try:
        async with get_sessionmaker()() as db:
            summary = await import_legacy(db, crypto, sqlite_path=Path(args.sqlite), key_path=Path(args.key),
                                          user_email=args.user, dry_run=args.dry_run)
    except (LegacyMigrationError, DecryptionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(("[dry-run] " if args.dry_run else "") + f"imported: {summary}")
    return 0


def check_config(_: argparse.Namespace) -> int:
    settings = get_settings()
    Crypto(settings.encryption_key_list)
    print(f"environment={settings.environment} tiktok_configured={settings.tiktok_configured} "
          f"audited={settings.tiktok_client_audited} scopes={settings.scope_list}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-user", help="create a user (password via --password, $QADAM_PASSWORD or prompt)")
    p.add_argument("email")
    p.add_argument("--name")
    p.add_argument("--password")
    p.add_argument("--admin", action="store_true")
    p.set_defaults(func=create_user)

    sub.add_parser("generate-key", help="print a new Fernet key for ENCRYPTION_KEYS").set_defaults(
        func=lambda _a: print(generate_key()) or 0)
    sub.add_parser("rotate-encryption", help="re-encrypt secrets with the primary key").set_defaults(
        func=rotate_encryption)
    sub.add_parser("check-config", help="validate settings").set_defaults(func=check_config)

    p = sub.add_parser("migrate-sqlite", help="import the legacy lab.db (tokens + events)")
    p.add_argument("--sqlite", required=True, help="path to legacy data/lab.db")
    p.add_argument("--key", required=True, help="path to legacy data/token.key")
    p.add_argument("--user", required=True, help="e-mail of the existing user that will own the account")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=migrate_sqlite)

    args = parser.parse_args(argv)
    result = args.func(args)
    if asyncio.iscoroutine(result):
        async def runner() -> int:
            try:
                return await result
            finally:
                await dispose_engine()

        return asyncio.run(runner())
    return int(result or 0)


if __name__ == "__main__":
    sys.exit(main())

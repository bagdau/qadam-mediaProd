"""One-off import of the legacy SQLite lab database into PostgreSQL.

The legacy ``data/lab.db`` contains a single TikTok token (encrypted with the Fernet key in
``data/token.key``) and an ``events`` journal. The import

* opens SQLite **read-only** (the legacy files are never modified),
* decrypts with the legacy key and re-encrypts with the current ``ENCRYPTION_KEYS``,
* attaches the account to an existing user (``--user``),
* converts events to ``audit_logs`` rows, idempotently (re-running does not duplicate),
* runs in one transaction (``--dry-run`` rolls it back) and never prints token values.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import Crypto
from app.core.redaction import redact
from app.models import AccountStatus, AuditLog, ConnectedAccount, User


class LegacyMigrationError(Exception):
    pass


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def read_legacy(db_path: Path, key_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        raise LegacyMigrationError(f"SQLite database not found: {db_path}")
    with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        token_row = conn.execute(
            "SELECT encrypted_payload, updated_at FROM tokens WHERE provider='tiktok'"
        ).fetchone() if "tokens" in tables else None
        events = conn.execute(
            "SELECT id, created_at, action, status, details FROM events ORDER BY id"
        ).fetchall() if "events" in tables else []

    token: dict[str, Any] | None = None
    if token_row:
        if not key_path.is_file():
            raise LegacyMigrationError(f"Legacy key file not found: {key_path}")
        try:
            token = json.loads(Fernet(key_path.read_bytes().strip()).decrypt(token_row[0].encode()))
        except (InvalidToken, ValueError) as exc:
            raise LegacyMigrationError("Cannot decrypt the legacy token with the given key file") from exc
        token["_updated_at"] = token_row[1]
    return {"token": token, "events": events}


async def import_legacy(
    db: AsyncSession,
    crypto: Crypto,
    *,
    sqlite_path: Path,
    key_path: Path,
    user_email: str,
    dry_run: bool = False,
) -> dict[str, int]:
    user = (await db.execute(select(User).where(User.email == user_email.strip().lower()))).scalar_one_or_none()
    if not user:
        raise LegacyMigrationError(f"Target user {user_email!r} does not exist; create it first")

    legacy = read_legacy(sqlite_path, key_path)
    summary = {"accounts": 0, "events": 0, "events_skipped": 0}

    token = legacy["token"]
    if token and token.get("access_token") and token.get("open_id"):
        issued = _parse_ts(token["_updated_at"])
        scopes = [s for s in str(token.get("scope", "")).split(",") if s]
        account = (
            await db.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.user_id == user.id,
                    ConnectedAccount.provider == "tiktok",
                    ConnectedAccount.provider_account_id == str(token["open_id"]),
                )
            )
        ).scalar_one_or_none()
        if account is None:
            account = ConnectedAccount(user_id=user.id, provider="tiktok", provider_account_id=str(token["open_id"]),
                                       connected_at=issued, scopes=scopes)
            db.add(account)
        account.scopes = scopes or account.scopes
        account.access_token_enc = crypto.encrypt(token["access_token"])
        if token.get("refresh_token"):
            account.refresh_token_enc = crypto.encrypt(token["refresh_token"])
            account.refresh_expires_at = issued + timedelta(seconds=int(token.get("refresh_expires_in", 31536000)))
        account.access_expires_at = issued + timedelta(seconds=int(token.get("expires_in", 86400)))
        account.status = AccountStatus.ACTIVE.value
        account.display_name = account.display_name or "Imported from legacy lab"
        summary["accounts"] = 1

    already = set(
        (await db.execute(text("SELECT details->>'legacy_id' FROM audit_logs WHERE details ? 'legacy_id'"))).scalars()
    )
    for event_id, created_at, action, status, details in legacy["events"]:
        if str(event_id) in already:
            summary["events_skipped"] += 1
            continue
        try:
            payload = json.loads(details) if details else {}
        except ValueError:
            payload = {}
        db.add(
            AuditLog(
                user_id=user.id,
                action=f"legacy.{action}",
                entity_type="legacy_event",
                entity_id=str(event_id),
                created_at=_parse_ts(created_at),
                details=redact({"legacy_id": str(event_id), "status": status, **payload}),
            )
        )
        summary["events"] += 1

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return summary

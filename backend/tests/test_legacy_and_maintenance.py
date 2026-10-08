from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from app.legacy_migration import LegacyMigrationError, import_legacy
from app.models import AuditLog, ConnectedAccount, MediaAsset, OAuthState, Publication, Session
from app.services import maintenance
from tests.conftest import make_account, make_media


# --------------------------------------------------------- legacy SQLite import
@pytest.fixture
def legacy_db(tmp_path):
    key = Fernet.generate_key()
    (tmp_path / "token.key").write_bytes(key)
    payload = {"access_token": "legacy-access-SECRET", "refresh_token": "legacy-refresh-SECRET", "open_id": "legacy-open-id",
               "scope": "user.info.basic,video.publish", "expires_in": 86400, "refresh_expires_in": 31536000}
    conn = sqlite3.connect(tmp_path / "lab.db")
    conn.executescript("""
        CREATE TABLE tokens (provider TEXT PRIMARY KEY, encrypted_payload TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, action TEXT NOT NULL,
                             status TEXT NOT NULL, details TEXT NOT NULL);""")
    conn.execute("INSERT INTO tokens VALUES (?,?,?)",
                 ("tiktok", Fernet(key).encrypt(json.dumps(payload).encode()).decode(), "2026-10-05T10:00:00+00:00"))
    conn.executemany("INSERT INTO events(created_at, action, status, details) VALUES (?,?,?,?)", [
        ("2026-10-05T10:00:01+00:00", "oauth", "success", json.dumps({"open_id": "legacy-open-id"})),
        ("2026-10-05T10:05:00+00:00", "direct_publish", "error", json.dumps({"message": "boom", "access_token": "LEAK"})),
    ])
    conn.commit()
    conn.close()
    return tmp_path


async def test_legacy_import_reencrypts_tokens_and_maps_events(sessions, crypto, user, legacy_db):
    async with sessions() as db:
        summary = await import_legacy(db, crypto, sqlite_path=legacy_db / "lab.db", key_path=legacy_db / "token.key",
                                      user_email="owner@example.com")
    assert summary == {"accounts": 1, "events": 2, "events_skipped": 0}
    async with sessions() as db:
        account = (await db.execute(select(ConnectedAccount))).scalar_one()
        logs = (await db.execute(select(AuditLog).where(AuditLog.entity_type == "legacy_event"))).scalars().all()
    assert account.user_id == user.id and account.scopes == ["user.info.basic", "video.publish"]
    assert crypto.decrypt(account.access_token_enc) == "legacy-access-SECRET"    # new key, readable
    assert "legacy-access" not in account.access_token_enc
    assert {log.action for log in logs} == {"legacy.oauth", "legacy.direct_publish"}
    assert all("LEAK" not in json.dumps(log.details) for log in logs)
    assert min(log.created_at for log in logs).year == 2026
    assert account.refresh_expires_at.year >= 2027


async def test_legacy_import_is_idempotent(sessions, crypto, user, legacy_db):
    kwargs = dict(sqlite_path=legacy_db / "lab.db", key_path=legacy_db / "token.key", user_email="owner@example.com")
    for _ in range(2):
        async with sessions() as db:
            summary = await import_legacy(db, crypto, **kwargs)
    assert summary == {"accounts": 1, "events": 0, "events_skipped": 2}
    async with sessions() as db:
        assert len((await db.execute(select(ConnectedAccount))).scalars().all()) == 1


async def test_dry_run_changes_nothing_and_source_is_untouched(sessions, crypto, user, legacy_db):
    before = (legacy_db / "lab.db").read_bytes()
    async with sessions() as db:
        summary = await import_legacy(db, crypto, sqlite_path=legacy_db / "lab.db", key_path=legacy_db / "token.key",
                                      user_email="owner@example.com", dry_run=True)
    assert summary["accounts"] == 1
    async with sessions() as db:
        assert (await db.execute(select(ConnectedAccount))).first() is None
        assert (await db.execute(select(AuditLog).where(AuditLog.entity_type == "legacy_event"))).first() is None
    assert (legacy_db / "lab.db").read_bytes() == before


async def test_empty_legacy_database_is_fine(sessions, crypto, user, tmp_path):
    conn = sqlite3.connect(tmp_path / "lab.db")
    conn.executescript("CREATE TABLE tokens (provider TEXT PRIMARY KEY, encrypted_payload TEXT, updated_at TEXT);"
                       "CREATE TABLE events (id INTEGER PRIMARY KEY, created_at TEXT, action TEXT, status TEXT, details TEXT);")
    conn.close()
    (tmp_path / "token.key").write_bytes(Fernet.generate_key())
    async with sessions() as db:
        summary = await import_legacy(db, crypto, sqlite_path=tmp_path / "lab.db", key_path=tmp_path / "token.key",
                                      user_email="owner@example.com")
    assert summary == {"accounts": 0, "events": 0, "events_skipped": 0}


async def test_legacy_import_errors(sessions, crypto, user, legacy_db):
    async with sessions() as db:
        with pytest.raises(LegacyMigrationError, match="does not exist"):
            await import_legacy(db, crypto, sqlite_path=legacy_db / "lab.db", key_path=legacy_db / "token.key",
                                user_email="nobody@example.com")
        (legacy_db / "wrong.key").write_bytes(Fernet.generate_key())
        with pytest.raises(LegacyMigrationError, match="decrypt"):
            await import_legacy(db, crypto, sqlite_path=legacy_db / "lab.db", key_path=legacy_db / "wrong.key",
                                user_email="owner@example.com")
        with pytest.raises(LegacyMigrationError, match="not found"):
            await import_legacy(db, crypto, sqlite_path=legacy_db / "missing.db", key_path=legacy_db / "token.key",
                                user_email="owner@example.com")


# ------------------------------------------------------------- maintenance
async def test_cleanup_auth_rows(sessions, user):
    old = datetime.now(UTC) - timedelta(days=40)
    async with sessions() as db:
        db.add_all([
            OAuthState(state_hash="a" * 64, user_id=user.id, expires_at=old),
            OAuthState(state_hash="b" * 64, user_id=user.id, expires_at=datetime.now(UTC) + timedelta(minutes=5)),
            Session(user_id=user.id, token_hash="c" * 64, last_seen_at=old, expires_at=old),
            Session(user_id=user.id, token_hash="d" * 64, last_seen_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=1)),
        ])
        await db.commit()
        assert await maintenance.cleanup_auth_rows(db) == {"oauth_states": 1, "sessions": 1}


async def test_media_cleanup_respects_active_publications(sessions, crypto, settings, user, media_dir):
    acc = await make_account(sessions, crypto, user.id)
    stale_unused = await make_media(sessions, settings, user.id)
    stale_in_use = await make_media(sessions, settings, user.id)
    stale_published = await make_media(sessions, settings, user.id)
    fresh = await make_media(sessions, settings, user.id)
    old = datetime.now(UTC) - timedelta(hours=72)
    async with sessions() as db:
        db.add(Publication(user_id=user.id, account_id=acc.id, media_id=stale_in_use.id, idempotency_key="use-key-1",
                           privacy_level="SELF_ONLY", status="PROCESSING"))
        db.add(Publication(user_id=user.id, account_id=acc.id, media_id=stale_published.id, idempotency_key="pub-key-1",
                           privacy_level="SELF_ONLY", status="PUBLISHED"))
        await db.commit()
        await db.execute(update(MediaAsset).where(MediaAsset.id.in_([stale_unused.id, stale_in_use.id, stale_published.id]))
                         .values(created_at=old))
        await db.execute(update(Publication).values(updated_at=old))
        await db.commit()
        result = await maintenance.cleanup_media(db, settings)
    assert result["media_purged"] == 2
    exists = lambda m: (settings.media_dir / m.storage_name).exists()  # noqa: E731
    assert not exists(stale_unused) and not exists(stale_published)
    assert exists(stale_in_use) and exists(fresh)
    async with sessions() as db:
        statuses = {m.id: m.status for m in (await db.execute(select(MediaAsset))).scalars()}
    assert statuses[stale_unused.id] == "deleted" and statuses[fresh.id] == "ready"


async def test_orphan_and_partial_files_are_removed(sessions, settings, media_dir, user):
    keep = await make_media(sessions, settings, user.id)
    partial = media_dir / ".upload-deadbeef.part"
    orphan = media_dir / "11111111-1111-4111-8111-111111111111.mp4"
    recent_orphan = media_dir / "22222222-2222-4222-8222-222222222222.mp4"
    for f in (partial, orphan, recent_orphan):
        f.write_bytes(b"x")
    long_ago = time.time() - 3 * 86400
    os.utime(partial, (long_ago, long_ago))
    os.utime(orphan, (long_ago, long_ago))
    async with sessions() as db:
        result = await maintenance.cleanup_media(db, settings)
    assert result["orphan_files"] == 2
    assert not partial.exists() and not orphan.exists()
    assert recent_orphan.exists() and (media_dir / keep.storage_name).exists()  # a fresh upload in flight is safe


async def test_cleanup_leaves_the_upload_spool_directory_alone(sessions, settings, media_dir, user):
    spool = media_dir / ".tmp"
    spool.mkdir(exist_ok=True)
    (spool / "tmpabc").write_bytes(b"in-flight multipart spool")
    async with sessions() as db:
        await maintenance.cleanup_media(db, settings)
    assert (spool / "tmpabc").exists()


async def test_app_start_creates_the_spool_directory(app, settings):
    assert (settings.media_dir / ".tmp").is_dir()

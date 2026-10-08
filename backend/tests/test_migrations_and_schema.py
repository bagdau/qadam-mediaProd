"""Database migration tests run against a scratch PostgreSQL database."""

from __future__ import annotations

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401
from app.db.base import Base
from tests.conftest import TEST_DB_URL, run_alembic

EXPECTED_TABLES = {"users", "sessions", "connected_accounts", "oauth_states", "media_assets", "publications",
                   "publication_events", "audit_logs"}


@pytest.fixture
async def scratch_url():
    name = f"qadam_mig_{uuid.uuid4().hex[:8]}"
    base = make_url(TEST_DB_URL)
    admin = create_async_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = base.set(database=name).render_as_string(hide_password=False)
    yield url
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    await admin.dispose()


async def tables(url: str) -> set[str]:
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))
        names = {r[0] for r in rows}
    await engine.dispose()
    return names - {"alembic_version"}


async def test_upgrade_creates_the_expected_schema_with_no_drift(scratch_url):
    run_alembic(scratch_url, "upgrade", "head")
    assert await tables(scratch_url) == EXPECTED_TABLES
    engine = create_async_engine(scratch_url, poolclass=NullPool)
    async with engine.connect() as conn:
        diff = await conn.run_sync(
            lambda sync_conn: compare_metadata(MigrationContext.configure(sync_conn, opts={"compare_type": True}),
                                               Base.metadata))
    await engine.dispose()
    assert diff == [], f"models and migrations diverged: {diff}"


async def test_migration_is_reversible_and_repeatable(scratch_url):
    run_alembic(scratch_url, "upgrade", "head")
    run_alembic(scratch_url, "downgrade", "base")
    assert await tables(scratch_url) == set()
    run_alembic(scratch_url, "upgrade", "head")
    run_alembic(scratch_url, "upgrade", "head")  # idempotent no-op
    assert await tables(scratch_url) == EXPECTED_TABLES


async def test_offline_sql_generation_works(scratch_url):
    out = run_alembic_offline(scratch_url)
    assert "CREATE TABLE users" in out and "CREATE TABLE publications" in out


def run_alembic_offline(url: str) -> str:
    import subprocess
    import sys

    from tests.conftest import BACKEND_DIR

    return subprocess.run([sys.executable, "-m", "alembic", "-x", f"url={url}", "upgrade", "head", "--sql"],
                          cwd=BACKEND_DIR, check=True, capture_output=True, text=True).stdout


async def test_column_types_follow_the_data_model(sessions):
    async with sessions() as db:
        rows = await db.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public'"))
        cols = {(t, c): d for t, c, d in rows}
    for table in EXPECTED_TABLES:
        assert cols[(table, "id")] == "uuid", table
        assert cols[(table, "created_at")] == "timestamp with time zone", table
    assert cols[("connected_accounts", "access_expires_at")] == "timestamp with time zone"
    assert cols[("publications", "finished_at")] == "timestamp with time zone"
    assert not [c for (t, c) in cols if c in {"access_token", "refresh_token", "client_secret", "password"}]
    assert ("connected_accounts", "access_token_enc") in cols and ("users", "password_hash") in cols


async def test_every_foreign_key_is_indexed_or_unique_leading_column(sessions):
    async with sessions() as db:
        fks = (await db.execute(text("""
            SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.contype = 'f'"""))).all()
        idx = (await db.execute(text("""
            SELECT i.indrelid::regclass::text AS tbl, a.attname AS col
            FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]"""))).all()
    leading = {(t, c) for t, c in idx}
    missing = [(t, c) for t, c in fks if (t, c) not in leading]
    # audit_logs.user_id and others are covered by composite indexes; anything uncovered is a bug
    assert missing == [], f"foreign keys without a supporting index: {missing}"


async def insert_user(db, email="u@example.com"):
    uid = uuid.uuid4()
    await db.execute(text("INSERT INTO users (id, email, password_hash, display_name, role) "
                          "VALUES (:i, :e, 'x', '', 'member')"), {"i": uid, "e": email})
    return uid


async def test_constraints_reject_bad_data(sessions):
    async with sessions() as db:
        await insert_user(db)
        await db.commit()
    for sql, params in [
        ("INSERT INTO users (id,email,password_hash,display_name,role) VALUES (gen_random_uuid(),'u@example.com','x','','member')", {}),  # duplicate email
        ("INSERT INTO users (id,email,password_hash,display_name,role) VALUES (gen_random_uuid(),'Upper@Example.com','x','','member')", {}),  # not lower case
        ("INSERT INTO users (id,email,password_hash,display_name,role) VALUES (gen_random_uuid(),'r@example.com','x','','root')", {}),  # bad role
        ("INSERT INTO sessions (id,user_id,token_hash,last_seen_at,expires_at) VALUES (gen_random_uuid(),gen_random_uuid(),'h',now(),now())", {}),  # FK
    ]:
        async with sessions() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text(sql), params)
                await db.commit()


async def test_publication_constraints_and_cascades(sessions, crypto, settings):
    from tests.conftest import make_account, make_media, make_user

    user = await make_user(sessions)
    acc = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id)
    ins = ("INSERT INTO publications (id,user_id,account_id,media_id,idempotency_key,privacy_level,status,mode,title,"
           "disable_comment,disable_duet,disable_stitch,brand_content_toggle,brand_organic_toggle,is_aigc,"
           "cover_timestamp_ms,uploaded_bytes,attempts,poll_count) VALUES (gen_random_uuid(),:u,:a,:m,:k,:p,:s,'DIRECT_POST',"
           ":t,true,true,true,false,false,false,0,0,0,0)")
    base = dict(u=user.id, a=acc.id, m=media.id, k="key-1", p="SELF_ONLY", s="QUEUED", t="ok")
    async with sessions() as db:
        await db.execute(text(ins), base)
        await db.commit()
    for override in (dict(k="key-1"), dict(k="key-2", p="EVERYONE"), dict(k="key-3", s="DONE"), dict(k="key-4", t="x" * 2201)):
        async with sessions() as db:
            with pytest.raises(IntegrityError):
                await db.execute(text(ins), {**base, **override})
                await db.commit()
    # a media row referenced by a publication cannot be hard-deleted
    async with sessions() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text("DELETE FROM media_assets WHERE id=:m"), {"m": media.id})
            await db.commit()
    # deleting the user removes everything that belongs to them
    async with sessions() as db:
        await db.execute(text("DELETE FROM publications WHERE user_id=:u"), {"u": user.id})
        await db.execute(text("DELETE FROM users WHERE id=:u"), {"u": user.id})
        await db.commit()
        for table in ("connected_accounts", "media_assets", "sessions"):
            assert (await db.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


async def test_same_tiktok_publish_id_cannot_be_used_twice(sessions, crypto, settings):
    from tests.conftest import make_account, make_media, make_user

    user = await make_user(sessions)
    acc = await make_account(sessions, crypto, user.id)
    media = await make_media(sessions, settings, user.id)
    from app.models import Publication

    async with sessions() as db:
        db.add(Publication(user_id=user.id, account_id=acc.id, media_id=media.id, idempotency_key="a-1",
                           privacy_level="SELF_ONLY", tiktok_publish_id="same"))
        await db.commit()
        db.add(Publication(user_id=user.id, account_id=acc.id, media_id=media.id, idempotency_key="b-2",
                           privacy_level="SELF_ONLY", tiktok_publish_id="same"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        # NULL publish ids may repeat (partial unique index)
        db.add_all([Publication(user_id=user.id, account_id=acc.id, media_id=media.id, idempotency_key=f"n-{i}0000",
                                privacy_level="SELF_ONLY") for i in range(2)])
        await db.commit()

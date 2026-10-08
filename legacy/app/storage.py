import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import ROOT


DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "lab.db"
KEY_PATH = DATA_DIR / "token.key"


def initialize() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tokens (
            provider TEXT PRIMARY KEY, encrypted_payload TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            action TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL
        )""")


def _cipher() -> Fernet:
    return Fernet(KEY_PATH.read_bytes())


def save_token(payload: dict) -> None:
    encrypted = _cipher().encrypt(json.dumps(payload).encode()).decode()
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT OR REPLACE INTO tokens(provider, encrypted_payload, updated_at) VALUES(?,?,?)",
            ("tiktok", encrypted, datetime.now(timezone.utc).isoformat()),
        )


def load_token() -> dict | None:
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT encrypted_payload FROM tokens WHERE provider='tiktok'").fetchone()
    return json.loads(_cipher().decrypt(row[0].encode())) if row else None


def delete_token() -> None:
    with sqlite3.connect(DB_PATH) as db:
        db.execute("DELETE FROM tokens WHERE provider='tiktok'")


def log_event(action: str, status: str, details: dict) -> None:
    safe = {key: value for key, value in details.items() if key not in {"access_token", "refresh_token", "client_secret"}}
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO events(created_at, action, status, details) VALUES(?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), action, status, json.dumps(safe, ensure_ascii=False)),
        )


def recent_events() -> list[dict]:
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute("SELECT created_at, action, status, details FROM events ORDER BY id DESC LIMIT 30").fetchall()
    return [{"created_at": row[0], "action": row[1], "status": row[2], "details": json.loads(row[3])} for row in rows]


from __future__ import annotations

import logging

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.crypto import Crypto, DecryptionError
from app.core.redaction import REDACTED, RedactingFilter, redact, redact_text
from app.core.security import hash_password, verify_password
from app.integrations.tiktok.chunks import MIB, plan_chunks
from app.services.media import media_path, sanitize_filename
from app.services.mediainfo import detect_content_type, mp4_duration_seconds
from app.services.publishing import backoff
from tests.helpers import make_mp4, make_webm


# ------------------------------------------------------------------ redaction
def test_redact_dict_masks_sensitive_keys_recursively():
    data = {"access_token": "abc", "nested": {"refresh_token": "def", "ok": 1},
            "list": [{"client_secret": "x"}], "error": {"code": "ok"}}
    out = redact(data)
    assert out["access_token"] == REDACTED and out["nested"]["refresh_token"] == REDACTED
    assert out["list"][0]["client_secret"] == REDACTED
    assert out["error"]["code"] == "ok" and out["nested"]["ok"] == 1
    assert data["access_token"] == "abc"  # input untouched


@pytest.mark.parametrize("text", [
    'POST failed: {"access_token": "act.SECRET123", "x": 1}',
    "Authorization: Bearer act.SECRET123",
    "https://x.test/cb?code=SECRET123&state=SECRET123",
    "refresh_token=SECRET123 expires=5",
    "upload https://upload.tiktokapis.com/video/upload?upload_id=1&sig=SECRET123 failed",
])
def test_redact_text_removes_secret_values(text):
    assert "SECRET123" not in redact_text(text)


def test_logging_filter_redacts_args_and_exceptions(caplog):
    logger = logging.getLogger("redaction-test")
    handler = logging.Handler()
    seen: list[str] = []
    handler.emit = lambda record: seen.append(handler.format(record))  # type: ignore[method-assign]
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.error("token is %s", "access_token=SUPERSECRET")
    assert seen and "SUPERSECRET" not in seen[0]


# --------------------------------------------------------------------- crypto
def test_crypto_roundtrip_and_rotation():
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    legacy = Crypto([old]).encrypt("tok")
    rotated = Crypto([new, old])
    assert rotated.decrypt(legacy) == "tok"
    upgraded = rotated.rotate(legacy)
    assert Crypto([new]).decrypt(upgraded) == "tok"  # decryptable without the old key
    with pytest.raises(DecryptionError):
        Crypto([new]).decrypt(legacy)


def test_crypto_ciphertext_does_not_contain_plaintext():
    assert "plain-token-value" not in Crypto([Fernet.generate_key().decode()]).encrypt("plain-token-value")


def test_crypto_requires_keys():
    with pytest.raises(RuntimeError):
        Crypto([])


# --------------------------------------------------------------------- config
@pytest.fixture
def clean_env(monkeypatch):
    for name in ("DATABASE_URL", "TIKTOK_CLIENT_SECRET", "TIKTOK_CLIENT_KEY", "POSTGRES_PASSWORD", "SECRET_KEY",
                 "ENCRYPTION_KEYS", "COOKIE_SECURE", "PUBLIC_URL", "ENVIRONMENT", "CORS_ORIGINS", "ALLOWED_HOSTS"):
        monkeypatch.delenv(name, raising=False)


def _prod(**overrides):
    base = dict(environment="production", secret_key="s" * 40, encryption_keys=Fernet.generate_key().decode(),
                cookie_secure=True, public_url="https://qadam-media.kz", postgres_password="pw",
                allowed_hosts=["qadam-media.kz"])
    base.update(overrides)
    return Settings(_env_file=None, _secrets_dir=None, **base)


def test_production_config_valid(clean_env):
    assert _prod().is_production


@pytest.mark.parametrize("override", [
    {"secret_key": "change-me"},
    {"secret_key": "short"},
    {"encryption_keys": ""},
    {"cookie_secure": False},
    {"public_url": "http://qadam-media.kz"},
    {"postgres_password": ""},
    {"allowed_hosts": ["*"]},
    {"tiktok_api_base": "http://localhost:9000/v2"},
])
def test_production_config_rejects_unsafe_values(clean_env, override):
    with pytest.raises(ValueError):
        _prod(**override)


def test_csv_settings_and_database_url_quoting(clean_env):
    s = Settings(_env_file=None, _secrets_dir=None, cors_origins="https://a.test, https://b.test",
                 postgres_password="p@ss:w/rd")
    assert s.cors_origins == ["https://a.test", "https://b.test"]
    assert "p%40ss%3Aw%2Frd" in s.sqlalchemy_url
    assert s.broker_url.endswith("/1") and s.result_backend_url.endswith("/2")


def test_secrets_are_read_from_files(tmp_path, clean_env):
    (tmp_path / "tiktok_client_secret").write_text("from-file\n")
    s = Settings(_env_file=None, _secrets_dir=str(tmp_path))
    assert s.tiktok_client_secret.get_secret_value() == "from-file"


def test_secrets_never_appear_in_repr(clean_env):
    s = Settings(_env_file=None, _secrets_dir=None, tiktok_client_secret="very-secret", secret_key="k" * 40)
    assert "very-secret" not in repr(s) and "k" * 40 not in repr(s)


# --------------------------------------------------------------------- passwords
def test_password_hashing():
    hashed = hash_password("Correct-Horse-Battery-9")
    assert hashed.startswith("$argon2") and "Correct" not in hashed
    assert verify_password("Correct-Horse-Battery-9", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("anything", None)


# ----------------------------------------------------------------------- chunks
def test_small_and_medium_files_use_one_chunk():
    for size in (1, 4 * MIB, 5 * MIB, 63 * MIB, 64 * MIB):
        plan = plan_chunks(size)
        assert (plan.chunk_size, plan.total_chunks) == (size, 1)
        assert plan.ranges() == [(0, size - 1)]


@pytest.mark.parametrize("size", [64 * MIB + 1, 100 * MIB, 250 * MIB + 17, 2048 * MIB + 5, 4096 * MIB])
def test_large_files_follow_tiktok_chunk_rules(size):
    plan = plan_chunks(size)
    ranges = plan.ranges()
    assert plan.total_chunks == size // plan.chunk_size == len(ranges) <= 1000
    assert 5 * MIB <= plan.chunk_size <= 64 * MIB
    assert ranges[0][0] == 0 and ranges[-1][1] == size - 1
    for (_, prev_last), (nxt_first, _) in zip(ranges, ranges[1:]):
        assert nxt_first == prev_last + 1  # contiguous
    sizes = [last - first + 1 for first, last in ranges]
    assert all(s == plan.chunk_size for s in sizes[:-1]) and sizes[-1] <= 128 * MIB


def test_chunk_plan_rejects_invalid_sizes():
    with pytest.raises(ValueError):
        plan_chunks(0)
    with pytest.raises(ValueError):
        plan_chunks(4096 * MIB + 1)


def test_range_at_offsets():
    plan = plan_chunks(200 * MIB)
    assert plan.range_at(0)[0] == 0
    assert plan.range_at(plan.chunk_size)[0] == plan.chunk_size
    assert plan.range_at(200 * MIB) is None


# ------------------------------------------------------------------ media helpers
def test_detects_real_formats_not_extensions():
    assert detect_content_type(make_mp4()[:512]) == "video/mp4"
    assert detect_content_type(make_webm()[:512]) == "video/webm"
    assert detect_content_type(b"MZ\x90\x00" + b"\x00" * 100) is None  # an .exe renamed to .mp4
    assert detect_content_type(b"<html><script>alert(1)</script>") is None


def test_mp4_duration_is_parsed_from_mvhd(tmp_path):
    f = tmp_path / "a.mp4"
    f.write_bytes(make_mp4(duration_s=37.5))
    assert mp4_duration_seconds(f) == pytest.approx(37.5)
    garbage = tmp_path / "b.mp4"
    garbage.write_bytes(b"\x00" * 100)
    assert mp4_duration_seconds(garbage) is None


@pytest.mark.parametrize("raw,expected", [
    ("../../etc/passwd", "passwd"),
    ("C:\\Users\\x\\clip.mp4", "clip.mp4"),
    ("my\x00 clip\n.mp4", "my clip.mp4"),
    ("", "video"),
    ("....", "video"),
    ("a" * 500 + ".mp4", None),
])
def test_filename_sanitising(raw, expected):
    result = sanitize_filename(raw)
    assert "/" not in result and "\\" not in result and ".." not in result.replace("....", "")
    assert len(result) <= 200
    if expected:
        assert result == expected


@pytest.mark.parametrize("name", ["../x.mp4", "..\\x.mp4", "/etc/passwd", "not-a-uuid.mp4",
                                  "11111111-1111-1111-1111-111111111111.exe",
                                  "11111111-1111-1111-1111-111111111111.mp4/../../x"])
def test_media_path_rejects_traversal(name, settings):
    with pytest.raises(ValueError):
        media_path(name, settings)


def test_media_path_accepts_generated_names(settings):
    p = media_path("11111111-1111-4111-8111-111111111111.mp4", settings)
    assert p.parent == settings.media_dir.resolve()


def test_backoff_grows_and_is_capped():
    delays = [backoff(n) for n in range(0, 12)]
    assert delays[0] < delays[3] < delays[5]
    assert max(delays) <= 900 * 1.2

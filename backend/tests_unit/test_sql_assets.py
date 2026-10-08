# ruff: noqa: S101

from pathlib import Path


def test_operational_sql_assets_are_read_only_or_explicit_cleanup() -> None:
    sql_dir = Path(__file__).resolve().parents[1] / "sql"
    scripts = sorted(sql_dir.glob("*.sql"))
    assert len(scripts) == 14
    for script in scripts:
        text = script.read_text(encoding="utf-8").strip()
        assert text.endswith(";")
        if text.startswith("DELETE"):
            assert script.name.startswith("cleanup_")
            assert "RETURNING" in text

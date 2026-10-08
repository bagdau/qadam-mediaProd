# ruff: noqa: S101

import pytest

from app.domain.content import normalize_caption, validate_caption
from app.domain.email import normalize_email
from app.domain.filenames import safe_display_filename


def test_caption_normalization_preserves_internal_spacing() -> None:
    assert normalize_caption("  hello  \r\nworld\t \n") == "hello\nworld"


def test_caption_rejects_more_than_utf16_limit() -> None:
    with pytest.raises(ValueError, match="2200"):
        validate_caption("😀" * 1101)


def test_identity_inputs_are_normalized_safely() -> None:
    assert normalize_email(" Owner@Example.COM ") == "owner@example.com"
    assert safe_display_filename("../uploads/video.mp4") == "video.mp4"

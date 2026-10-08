def content_range(first: int, last: int, total: int) -> str:
    if first < 0 or last < first or total <= last:
        raise ValueError("invalid upload byte range")
    return f"bytes {first}-{last}/{total}"


def uploaded_percent(uploaded: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(100, round(uploaded * 100 / total)))

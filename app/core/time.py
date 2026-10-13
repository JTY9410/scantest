from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    """Laravel 직렬화 형식(2026-10-13T04:43:17.000000Z)으로 변환한다."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def local_display(value: datetime | None) -> str:
    """관리자 화면 표시용(한국 시간)."""
    if value is None:
        return "-"
    from zoneinfo import ZoneInfo

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")

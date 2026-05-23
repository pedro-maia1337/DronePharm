from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo

INVALID_DATETIME_MESSAGE = (
    "janela_fim deve ser uma string ISO 8601 com timezone "
    "(ex: 2026-06-01T18:00:00Z)."
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=LOCAL_TIMEZONE).astimezone(timezone.utc)
    return value.astimezone(timezone.utc)


def to_db_datetime(value: datetime) -> datetime:
    return ensure_datetime_utc(value).replace(tzinfo=None)


def parse_datetime_utc(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_datetime_utc(value)
    if not isinstance(value, str):
        raise ValueError(INVALID_DATETIME_MESSAGE)

    text = value.strip()
    if not text:
        raise ValueError(INVALID_DATETIME_MESSAGE)

    normalized = f"{text[:-1]}+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(INVALID_DATETIME_MESSAGE) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(INVALID_DATETIME_MESSAGE)
    return parsed.astimezone(timezone.utc)

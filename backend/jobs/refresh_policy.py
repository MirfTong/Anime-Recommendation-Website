"""Scheduling policy shared by the bounded catalogue worker and its tests."""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect


def utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


@dataclass(frozen=True)
class RefreshPolicy:
    airing_days: int = 3
    recent_days: int = 7
    stable_days: int = 60
    retry_days: int = 1
    discovery_days: int = 14

    def __post_init__(self):
        if any(getattr(self, field) <= 0 for field in self.__dataclass_fields__):
            raise ValueError("Refresh intervals must be positive")

    @classmethod
    def from_env(cls):
        return cls(
            **{
                field: int(os.getenv(f"ETL_{field.upper()}", str(default.default)))
                for field, default in cls.__dataclass_fields__.items()
            }
        )

    def detail_days(self, data: dict, now: datetime) -> int:
        status = str(data.get("status") or "").strip().upper().replace(" ", "_")
        if status in {"CURRENTLY_AIRING", "AIRING", "PUBLISHING"}:
            return self.airing_days
        if status not in {"FINISHED", "FINISHED_AIRING"}:
            return self.recent_days
        dates = data.get("aired") or data.get("published")
        end = dates.get("to") if isinstance(dates, dict) else None
        try:
            ended = utc(datetime.fromisoformat(end.replace("Z", "+00:00")))
        except AttributeError, TypeError, ValueError:
            # A start/publication year does not prove when a long-running title ended.
            return self.recent_days
        return (
            self.recent_days if now - ended < timedelta(days=90) else self.stable_days
        )


def next_streaming_check(
    streak: int, *, empty: bool, failed: bool, now: datetime, policy: RefreshPolicy
):
    if failed:
        return streak, now + timedelta(days=policy.retry_days)
    if empty:
        streak = min(streak + 1, 3)
        return streak, now + timedelta(days=(7, 30, 90)[streak - 1])
    return 0, now + timedelta(days=policy.stable_days)


def content_snapshot(row):
    """Compare business data, excluding ETL bookkeeping timestamps."""
    state = inspect(row)
    columns = tuple(
        (attribute.key, getattr(row, attribute.key))
        for attribute in inspect(type(row)).column_attrs
        if not attribute.key.startswith("last_") and attribute.key not in state.unloaded
    )
    links = []
    for relationship, entity, fields in (
        ("genre_links", "genre", ("name",)),
        ("studio_links", "studio", ("name", "mal_id")),
        ("streaming_links", "streaming_service", ("name",)),
        ("author_links", "author", ("name", "mal_id")),
    ):
        if not hasattr(type(row), relationship) or relationship in state.unloaded:
            continue
        values = [
            (
                tuple(getattr(getattr(link, entity), field) for field in fields),
                getattr(link, "url", None),
                getattr(link, "role", None),
            )
            for link in getattr(row, relationship)
            if not inspect(link).deleted
            and (state.session is None or link not in state.session.deleted)
        ]
        links.append((relationship, sorted(values, key=repr)))
    return repr((columns, links))

r"""Run the resumable Anime, Manga, and Manhwa catalogue synchronization."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import selectinload

from backend.app import app
from backend.jobs.manga_etl import (
    DEFAULT_MANGA_REFRESH_LIMIT,
    MangaCatalogueSyncResult,
    MangaRefreshResult,
    refresh_manga_catalogue,
    remove_adult_manga,
    report_manga_catalogue,
    report_manga_cleanup,
    report_manga_refresh,
    sync_manga_catalogue,
)
from backend.models import Anime, AnimeGenre, Genre, JikanSyncState, db
from backend.schema import ensure_anime_schema, refresh_catalogue_facets
from backend.services.jikan_client import (
    JikanAnimePage,
    JikanSeasonPage,
    JikanTemporaryError,
    get_anime,
    get_anime_catalogue_page,
    get_anime_full,
    get_season_anime,
    get_season_page,
)


SKIPPABLE_JIKAN_STATUS_CODES = frozenset({404, 429, 500, 502, 503, 504})
TEMPORARY_JIKAN_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
JIKAN_SEASONS = frozenset({"winter", "spring", "summer", "fall"})
ADULT_GENRE_NAMES = frozenset({"hentai", "erotica"})
TYPE_ALIASES = {"TV SPECIAL": "SPECIAL"}
ANIME_STATUS_ALIASES = {
    "AIRING": "CURRENTLY_AIRING",
    "CURRENTLY_AIRING": "CURRENTLY_AIRING",
    "FINISHED": "FINISHED_AIRING",
    "FINISHED_AIRING": "FINISHED_AIRING",
    "NOT_YET_AIRED": "NOT_YET_AIRED",
    "NOT_YET_AIRING": "NOT_YET_AIRED",
}
SUPPLEMENTAL_PROVIDER_TYPES = ("ova", "ona", "special", "tv_special")
SUPPLEMENTAL_STATE_KEYS = {
    anime_type: f"bulk:catalogue:{anime_type}:v1"
    for anime_type in SUPPLEMENTAL_PROVIDER_TYPES
}
CURRENT_SEASON_MAX_PAGES_PER_RUN = 10
DEFAULT_SEASON_BACKFILL_LIMIT = 1000
BULK_SEASON_MAX_PAGES_PER_RUN = 40
BULK_SEASON_MAX_CONSECUTIVE_FAILURES = 3
BULK_SEASON_STATE_KEY = "bulk:tv-catalogue-seasons:v2"
DEGRADED_SUCCESS_RATE = 0.25


@dataclass(frozen=True)
class AnimeFetchResult:
    data: dict[str, Any] | None
    failure: str | None = None


@dataclass
class CatalogueRefreshResult:
    selected: int = 0
    updated: int = 0
    removed_hentai: int = 0
    missing_mal_id: int = 0
    not_found: int = 0
    temporary_errors: int = 0
    invalid_payloads: int = 0

    @property
    def skipped(self) -> int:
        return (
            self.missing_mal_id
            + self.not_found
            + self.temporary_errors
            + self.invalid_payloads
        )

    @property
    def success_rate(self) -> float:
        successful = self.updated + self.removed_hentai
        return successful / self.selected if self.selected else 0.0


@dataclass
class SeasonPageApplyResult:
    saved: int = 0
    inserted: int = 0
    removed_hentai: int = 0
    skipped: int = 0
    seasons_assigned: int = 0


@dataclass
class CurrentSeasonSyncResult:
    saved: int = 0
    inserted: int = 0
    removed_hentai: int = 0
    skipped: int = 0
    seasons_assigned: int = 0
    pages_completed: int = 0
    pages_failed: int = 0
    complete: bool = False
    next_page: int = 1


@dataclass
class SeasonBackfillResult:
    selected: int = 0
    updated: int = 0
    removed_hentai: int = 0
    seasons_assigned: int = 0
    still_missing: int = 0
    not_found: int = 0
    temporary_errors: int = 0
    invalid_payloads: int = 0

    @property
    def success_rate(self) -> float:
        successful = self.updated + self.removed_hentai
        return successful / self.selected if self.selected else 0.0


@dataclass
class BulkSeasonSyncResult:
    pages_attempted: int = 0
    pages_completed: int = 0
    pages_failed: int = 0
    updated: int = 0
    inserted: int = 0
    removed_hentai: int = 0
    seasons_assigned: int = 0
    complete: bool = False
    next_page: int = 1


@dataclass(frozen=True)
class SupplementalCatalogueSyncResult:
    scans: dict[str, BulkSeasonSyncResult]

    @property
    def inserted(self) -> int:
        return sum(scan.inserted for scan in self.scans.values())

    @property
    def updated(self) -> int:
        return sum(scan.updated for scan in self.scans.values())

    @property
    def pages_completed(self) -> int:
        return sum(scan.pages_completed for scan in self.scans.values())

    @property
    def pages_failed(self) -> int:
        return sum(scan.pages_failed for scan in self.scans.values())

    @property
    def removed_hentai(self) -> int:
        return sum(scan.removed_hentai for scan in self.scans.values())


@dataclass(frozen=True)
class SeasonCoverage:
    total_tv: int
    classified_tv: int

    @property
    def rate(self) -> float:
        return self.classified_tv / self.total_tv if self.total_tv else 0.0


@dataclass(frozen=True)
class ScheduledSyncResult:
    current_season: CurrentSeasonSyncResult
    bulk_seasons: BulkSeasonSyncResult
    supplemental_catalogue: SupplementalCatalogueSyncResult
    season_backfill: SeasonBackfillResult
    catalogue: CatalogueRefreshResult
    manga_catalogue: MangaCatalogueSyncResult
    manga_refresh: MangaRefreshResult
    coverage: SeasonCoverage
    removed_hentai: int
    removed_adult_manga: int


def _names(entries: Any) -> list[str]:
    """Return unique, non-empty Jikan category names in API order."""
    if not isinstance(entries, list):
        return []
    names = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return list(dict.fromkeys(names))


def _detailed_genres(data: dict[str, Any], current: list[str]) -> list[str]:
    """Add Jikan genre classifications without discarding richer CSV tags."""
    jikan_names = []
    for field in ("genres", "explicit_genres", "themes", "demographics"):
        jikan_names.extend(name.lower() for name in _names(data.get(field)))
    return list(dict.fromkeys([*current, *jikan_names]))


def _is_hentai(data: dict[str, Any]) -> bool:
    """Return whether Jikan classifies an anime as adult-only."""
    for field_name in ("genres", "explicit_genres", "themes", "demographics"):
        if any(
            name.casefold() in ADULT_GENRE_NAMES
            for name in _names(data.get(field_name))
        ):
            return True
    rating = data.get("rating")
    return isinstance(rating, str) and "hentai" in rating.casefold()


def _valid_score(value: Any) -> float | None:
    """Return a published Jikan score; Jikan uses zero for unknown scores."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _anime_type(value: Any, *, fallback: str = "UNKNOWN") -> str:
    """Map provider and legacy type labels onto one canonical value."""
    if not isinstance(value, str) or not value.strip():
        return fallback
    normalized = " ".join(value.replace("_", " ").split()).upper()
    return TYPE_ALIASES.get(normalized, normalized)


def _anime_status(value: Any) -> str | None:
    """Map provider airing labels onto stable database and API values."""
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = "_".join(value.replace("-", " ").split()).upper()
    return ANIME_STATUS_ALIASES.get(normalized)


def _synopsis(value: Any) -> str | None:
    """Normalize Jikan's optional plot summary for storage."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _season(value: Any) -> str | None:
    """Normalize Jikan's optional season field to supported filter values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in JIKAN_SEASONS else None


def _is_tv(anime_type: Any) -> bool:
    return isinstance(anime_type, str) and anime_type.strip().upper() == "TV"


def _season_from_air_date(data: dict[str, Any]) -> str | None:
    """Infer a TV premiere season when the provider omits its season field."""
    aired = data.get("aired")
    if not isinstance(aired, dict):
        return None

    month = None
    start = aired.get("from")
    if isinstance(start, str):
        match = re.match(r"^\d{4}-(\d{2})", start.strip())
        if match:
            month = int(match.group(1))

    if month is None:
        properties = aired.get("prop")
        from_properties = (
            properties.get("from") if isinstance(properties, dict) else None
        )
        candidate = (
            from_properties.get("month") if isinstance(from_properties, dict) else None
        )
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            month = candidate

    if month is None or not 1 <= month <= 12:
        return None
    return ("winter", "spring", "summer", "fall")[(month - 1) // 3]


def _jpg_images(data: dict[str, Any]) -> dict[str, Any]:
    images = data.get("images")
    if not isinstance(images, dict):
        return {}
    jpg_images = images.get("jpg")
    return jpg_images if isinstance(jpg_images, dict) else {}


def _update_anime(anime: Anime, data: dict[str, Any], genres: dict[str, Genre]) -> None:
    """Map one Jikan anime object onto an existing catalogue row."""
    anime.is_adult = _is_hentai(data)
    anime.title = data.get("title") or anime.title
    anime.alternative_title = (
        data.get("title_english")
        or data.get("title_japanese")
        or anime.alternative_title
    )
    if "synopsis" in data:
        anime.synopsis = _synopsis(data.get("synopsis"))
    anime.type = _anime_type(data.get("type"), fallback=_anime_type(anime.type))
    if "status" in data:
        incoming_status = _anime_status(data.get("status"))
        if incoming_status is not None:
            anime.status = incoming_status
    incoming_season = _season(data.get("season"))
    if incoming_season is None and _is_tv(anime.type):
        incoming_season = _season_from_air_date(data)
    if incoming_season is not None:
        anime.season = incoming_season
    elif not _is_tv(anime.type):
        # Films and specials legitimately have no broadcast season. A sparse
        # TV response must not erase a season obtained from a seasonal listing.
        anime.season = None
    if "year" in data:
        anime.year = data.get("year")
    if "score" in data:
        # An explicit null/zero means MAL does not currently publish a score.
        # Clear stale CSV ratings instead of presenting them as authoritative.
        anime.score = _valid_score(data.get("score"))
    if "episodes" in data:
        anime.episodes = data.get("episodes")
    anime.mal_url = data.get("url") or anime.mal_url

    jpg_images = _jpg_images(data)
    anime.image_url = (
        jpg_images.get("large_image_url")
        or jpg_images.get("image_url")
        or anime.image_url
    )
    if "relations" in data:
        relations = data.get("relations")
        anime.sequel = any(
            isinstance(relation, dict) and relation.get("relation") == "Sequel"
            for relation in (relations if isinstance(relations, list) else [])
        )

    genre_names = _names(data.get("genres"))
    if genre_names:
        anime.legacy_genres = genre_names
        links_by_name = {link.genre.name: link for link in anime.genre_links}
        for name in genre_names:
            genre = genres.get(name)
            if genre is None:
                genre = Genre(name=name)
                db.session.add(genre)
                genres[name] = genre
            if name not in links_by_name:
                anime.genre_links.append(AnimeGenre(genre=genre))
        for name, link in links_by_name.items():
            if name not in genre_names:
                db.session.delete(link)

    anime.genres_detailed = _detailed_genres(data, anime.genres_detailed or [])
    anime.last_jikan_sync = datetime.now(timezone.utc)


def _new_anime(data: dict[str, Any]) -> Anime:
    """Create a catalogue row from a Jikan anime object."""
    images = _jpg_images(data)
    mal_id = data["mal_id"]
    anime_type = _anime_type(data.get("type"))
    season = _season(data.get("season"))
    if season is None and _is_tv(anime_type):
        season = _season_from_air_date(data)
    return Anime(
        animeID=-mal_id,
        mal_id=mal_id,
        title=data.get("title") or f"MAL anime {mal_id}",
        alternative_title=data.get("title_english") or data.get("title_japanese"),
        synopsis=_synopsis(data.get("synopsis")),
        type=anime_type,
        season=season,
        status=_anime_status(data.get("status")),
        year=data.get("year"),
        score=_valid_score(data.get("score")),
        is_adult=_is_hentai(data),
        episodes=data.get("episodes"),
        mal_url=data.get("url") or f"https://myanimelist.net/anime/{mal_id}",
        sequel=False,
        image_url=images.get("large_image_url") or images.get("image_url") or "",
        legacy_genres=[],
        genres_detailed=[],
    )


def _ensure_schema() -> None:
    ensure_anime_schema()


def remove_hentai_anime() -> int:
    """Delete anime classified as Hentai or Erotica in stored genres."""
    with app.app_context():
        _ensure_schema()
        anime_ids = list(
            db.session.scalars(
                text(
                    "SELECT DISTINCT anime.anime_id FROM anime "
                    "WHERE anime.is_adult = TRUE OR EXISTS ("
                    "SELECT 1 FROM anime_genre "
                    "JOIN genre ON genre.id = anime_genre.genre_id "
                    "WHERE anime_genre.anime_id = anime.anime_id "
                    "AND LOWER(TRIM(genre.name)) IN ('hentai', 'erotica')"
                    ") OR EXISTS ("
                    "SELECT 1 FROM unnest(anime.genres) AS legacy(value) "
                    "WHERE LOWER(TRIM(legacy.value)) IN ('hentai', 'erotica')"
                    ") OR EXISTS ("
                    "SELECT 1 FROM unnest(anime.genres_detailed) AS detail(value) "
                    "WHERE LOWER(TRIM(detail.value)) IN ('hentai', 'erotica')"
                    ")"
                )
            )
        )
        if anime_ids:
            db.session.execute(
                delete(AnimeGenre).where(AnimeGenre.anime_id.in_(anime_ids))
            )
            db.session.execute(delete(Anime).where(Anime.animeID.in_(anime_ids)))
        db.session.commit()
        return len(anime_ids)


def _fetch_anime_data(
    mal_id: int, fetch_anime: Callable[[int], dict[str, Any]]
) -> AnimeFetchResult:
    """Fetch one record while preserving an actionable failure category."""
    try:
        payload = fetch_anime(mal_id)
    except JikanTemporaryError:
        return AnimeFetchResult(None, "temporary")
    except HTTPError as error:
        status_code = error.code
        error.close()
        if status_code == 404:
            return AnimeFetchResult(None, "not_found")
        if status_code in TEMPORARY_JIKAN_STATUS_CODES:
            return AnimeFetchResult(None, "temporary")
        db.session.rollback()
        raise

    data = payload.get("data")
    if not isinstance(data, dict):
        return AnimeFetchResult(None, "invalid_payload")
    return AnimeFetchResult(data)


def _commit_completed_batch(processed_count: int, batch_size: int) -> None:
    if processed_count % batch_size == 0:
        db.session.commit()


def _mark_jikan_attempt(anime: Anime) -> None:
    db.session.execute(
        text(
            "UPDATE anime SET last_jikan_attempt = :attempted "
            "WHERE anime_id = :anime_id"
        ),
        {"attempted": datetime.now(timezone.utc), "anime_id": anime.animeID},
    )


def refresh_catalogue(
    anime_ids: Iterable[int] | None = None,
    *,
    limit: int | None = None,
    batch_size: int = 25,
    fetch_anime: Callable[[int], dict[str, Any]] = get_anime_full,
) -> CatalogueRefreshResult:
    """Refresh the oldest-attempted rows and return classified health metrics."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be positive")

    with app.app_context():
        _ensure_schema()
        statement = select(Anime).options(
            selectinload(Anime.genre_links).selectinload(AnimeGenre.genre)
        )
        if anime_ids is not None:
            statement = statement.where(Anime.mal_id.in_(list(anime_ids)))
        if anime_ids is None:
            statement = statement.order_by(
                text("last_jikan_attempt ASC NULLS FIRST"), Anime.animeID
            )
        else:
            statement = statement.order_by(Anime.mal_id)
        if limit is not None:
            statement = statement.limit(limit)
        anime_rows = list(db.session.scalars(statement))
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
        result = CatalogueRefreshResult(selected=len(anime_rows))

        for attempted, anime in enumerate(anime_rows, start=1):
            _mark_jikan_attempt(anime)
            if anime.mal_id is None:
                result.missing_mal_id += 1
            else:
                fetched = _fetch_anime_data(anime.mal_id, fetch_anime)
                if fetched.data is not None:
                    if _is_hentai(fetched.data):
                        db.session.delete(anime)
                        result.removed_hentai += 1
                    else:
                        _update_anime(anime, fetched.data, genres)
                        result.updated += 1
                elif fetched.failure == "not_found":
                    result.not_found += 1
                elif fetched.failure == "temporary":
                    result.temporary_errors += 1
                else:
                    result.invalid_payloads += 1
            _commit_completed_batch(attempted, batch_size)

        db.session.commit()
        return result


def _prepared_season_entry(
    entry: dict[str, Any], year: int | None, season: str | None
) -> dict[str, Any]:
    """Copy listing data and make the requested season authoritative."""
    data = dict(entry)
    if year is not None:
        data["year"] = year
    if season is not None and (data.get("type") is None or _is_tv(data.get("type"))):
        data["season"] = season
    return data


def sync_season(
    year: int | None = None,
    season: str | None = None,
    *,
    limit: int | None = None,
    batch_size: int = 25,
    fetch_season: Callable[
        [int | None, str | None], list[dict[str, Any]]
    ] = get_season_anime,
) -> tuple[int, int]:
    """Import a complete named season; continuous current imports use cursors."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    seasonal_entries = fetch_season(year, season)
    hentai_ids = {
        entry["mal_id"]
        for entry in seasonal_entries
        if isinstance(entry, dict)
        and isinstance(entry.get("mal_id"), int)
        and not isinstance(entry.get("mal_id"), bool)
        and entry["mal_id"] > 0
        and _is_hentai(entry)
    }
    seasonal_data = {
        entry["mal_id"]: _prepared_season_entry(entry, year, season)
        for entry in seasonal_entries
        if isinstance(entry, dict)
        and isinstance(entry.get("mal_id"), int)
        and not isinstance(entry.get("mal_id"), bool)
        and entry["mal_id"] > 0
        and not _is_hentai(entry)
    }
    for mal_id in hentai_ids:
        seasonal_data.pop(mal_id, None)
    seasonal_ids = list(seasonal_data)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        seasonal_ids = seasonal_ids[:limit]

    with app.app_context():
        _ensure_schema()
        queried_ids = list(dict.fromkeys([*seasonal_ids, *hentai_ids]))
        existing = {
            anime.mal_id: anime
            for anime in db.session.scalars(
                select(Anime)
                .where(Anime.mal_id.in_(queried_ids))
                .options(selectinload(Anime.genre_links).selectinload(AnimeGenre.genre))
            )
        }
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
        for mal_id in hentai_ids:
            anime = existing.pop(mal_id, None)
            if anime is not None:
                db.session.delete(anime)
        saved = 0
        skipped = len(seasonal_entries) - len(seasonal_data)
        for mal_id in seasonal_ids:
            data = seasonal_data[mal_id]
            anime = existing.get(mal_id)
            if anime is None:
                anime = _new_anime(data)
                db.session.add(anime)
                existing[mal_id] = anime
            _update_anime(anime, data, genres)
            saved += 1
            _commit_completed_batch(saved, batch_size)
        db.session.commit()
        return saved, skipped


def _sync_state(key: str) -> JikanSyncState:
    state = db.session.get(JikanSyncState, key)
    if state is None:
        state = JikanSyncState(key=key, next_page=1)
        db.session.add(state)
    return state


def _next_page(key: str) -> int:
    with app.app_context():
        state = db.session.get(JikanSyncState, key)
        return max(1, state.next_page) if state is not None else 1


def _record_page_error(key: str, page: int, error: BaseException) -> None:
    with app.app_context():
        state = _sync_state(key)
        state.next_page = page
        state.last_attempt_at = datetime.now(timezone.utc)
        state.last_error = f"{type(error).__name__}: {error}"[:500]
        db.session.commit()


def _apply_season_page(
    page_result: JikanSeasonPage | JikanAnimePage,
    *,
    state_key: str,
    year: int | None,
    season: str | None,
    discover_missing: bool,
    tv_only: bool,
    allowed_types: frozenset[str] | None = None,
    default_type: str | None = None,
) -> SeasonPageApplyResult:
    """Persist one page and its next-page cursor in the same transaction."""
    data_by_mal_id: dict[int, dict[str, Any]] = {}
    hentai_ids: set[int] = set()
    for entry in page_result.entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("mal_id"), int)
            or isinstance(entry.get("mal_id"), bool)
            or entry["mal_id"] <= 0
        ):
            continue
        if _is_hentai(entry):
            hentai_ids.add(entry["mal_id"])
            continue
        data = _prepared_season_entry(entry, year, season)
        if not isinstance(data.get("type"), str) and default_type is not None:
            data["type"] = default_type
        if tv_only and not _is_tv(data.get("type")):
            continue
        if (
            allowed_types is not None
            and _anime_type(data.get("type")) not in allowed_types
        ):
            continue
        data_by_mal_id[entry["mal_id"]] = data

    for mal_id in hentai_ids:
        data_by_mal_id.pop(mal_id, None)
    ids = list(dict.fromkeys([*data_by_mal_id, *hentai_ids]))
    with app.app_context():
        statement = select(Anime).where(Anime.mal_id.in_(ids))
        statement = statement.options(
            selectinload(Anime.genre_links).selectinload(AnimeGenre.genre)
        )
        existing = {anime.mal_id: anime for anime in db.session.scalars(statement)}
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
        result = SeasonPageApplyResult(
            skipped=len(page_result.entries) - len(data_by_mal_id)
        )

        for mal_id in hentai_ids:
            anime = existing.pop(mal_id, None)
            if anime is not None:
                db.session.delete(anime)
                result.removed_hentai += 1

        for mal_id, data in data_by_mal_id.items():
            anime = existing.get(mal_id)
            previous_season = anime.season if anime is not None else None
            if anime is None:
                if not discover_missing:
                    continue
                anime = _new_anime(data)
                db.session.add(anime)
                existing[mal_id] = anime
                result.inserted += 1
            if tv_only and season is not None:
                data = {**data, "season": season}
            _update_anime(anime, data, genres)
            result.saved += 1
            if previous_season is None and anime.season is not None:
                result.seasons_assigned += 1

        state = _sync_state(state_key)
        state.next_page = page_result.page + 1 if page_result.has_next_page else 1
        state.last_attempt_at = datetime.now(timezone.utc)
        state.last_error = None
        if not page_result.has_next_page:
            state.last_completed_at = datetime.now(timezone.utc)
        db.session.commit()
        return result


def _current_season_identity(now: datetime | None = None) -> tuple[int, str]:
    japan_time = timezone(timedelta(hours=9))
    current = (now or datetime.now(timezone.utc)).astimezone(japan_time)
    seasons = ("winter", "spring", "summer", "fall")
    return current.year, seasons[(current.month - 1) // 3]


def sync_current_season(
    *,
    max_pages: int = CURRENT_SEASON_MAX_PAGES_PER_RUN,
    fetch_page: Callable[..., JikanSeasonPage] = get_season_page,
    now: datetime | None = None,
) -> CurrentSeasonSyncResult:
    """Resume the current season cursor and atomically save each fetched page."""
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    year, season = _current_season_identity(now)
    state_key = f"current:{year}:{season}"
    with app.app_context():
        _ensure_schema()
    page = _next_page(state_key)
    result = CurrentSeasonSyncResult(next_page=page)

    for _ in range(max_pages):
        try:
            fetched = fetch_page(None, None, page=page)
        except JikanTemporaryError as error:
            _record_page_error(state_key, page, error)
            result.pages_failed += 1
            break
        except HTTPError as error:
            status_code = error.code
            error.close()
            if status_code not in SKIPPABLE_JIKAN_STATUS_CODES:
                raise
            resume_page = 1 if status_code == 404 and page > 1 else page
            _record_page_error(state_key, resume_page, error)
            result.pages_failed += 1
            result.next_page = resume_page
            break

        applied = _apply_season_page(
            fetched,
            state_key=state_key,
            year=year,
            season=season,
            discover_missing=True,
            tv_only=False,
        )
        result.saved += applied.saved
        result.inserted += applied.inserted
        result.removed_hentai += applied.removed_hentai
        result.skipped += applied.skipped
        result.seasons_assigned += applied.seasons_assigned
        result.pages_completed += 1
        if not fetched.has_next_page:
            result.complete = True
            result.next_page = 1
            break
        page = fetched.page + 1
        result.next_page = page

    return result


def _sync_bulk_anime_type(
    *,
    anime_type: str,
    state_key: str,
    discover_missing: bool,
    max_pages: int = BULK_SEASON_MAX_PAGES_PER_RUN,
    max_consecutive_failures: int = BULK_SEASON_MAX_CONSECUTIVE_FAILURES,
    fetch_page: Callable[..., JikanAnimePage] = get_anime_catalogue_page,
) -> BulkSeasonSyncResult:
    """Resume one provider-type catalogue cursor and persist its pages.

    One successful request can update up to 50 anime. Temporary failures
    retry the same page a bounded number of times, then preserve its cursor for
    the next scheduled run so valid rows are never silently skipped.
    """
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if max_consecutive_failures <= 0:
        raise ValueError("max_consecutive_failures must be positive")

    with app.app_context():
        _ensure_schema()
    page = _next_page(state_key)
    result = BulkSeasonSyncResult(next_page=page)
    consecutive_failures = 0

    for _ in range(max_pages):
        result.pages_attempted += 1
        try:
            fetched = fetch_page(anime_type=anime_type, page=page)
        except JikanTemporaryError as error:
            _record_page_error(state_key, page, error)
            result.pages_failed += 1
            result.next_page = page
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                break
            continue
        except HTTPError as error:
            status_code = error.code
            error.close()
            if status_code not in SKIPPABLE_JIKAN_STATUS_CODES:
                raise
            if status_code == 404 and page > 1:
                _record_page_error(state_key, 1, error)
                result.pages_failed += 1
                result.complete = True
                result.next_page = 1
                break
            _record_page_error(state_key, page, error)
            result.pages_failed += 1
            result.next_page = page
            # A sustained 429 is a provider-wide quota signal. Retrying later
            # preserves this page instead of silently losing valid rows.
            if status_code == 429:
                break
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                break
            continue

        consecutive_failures = 0
        applied = _apply_season_page(
            fetched,
            state_key=state_key,
            year=None,
            season=None,
            discover_missing=discover_missing,
            tv_only=False,
            allowed_types=frozenset({_anime_type(anime_type)}),
            default_type=_anime_type(anime_type),
        )
        result.pages_completed += 1
        result.updated += applied.saved - applied.inserted
        result.inserted += applied.inserted
        result.removed_hentai += applied.removed_hentai
        result.seasons_assigned += applied.seasons_assigned
        if not fetched.has_next_page:
            result.complete = True
            result.next_page = 1
            break
        page = fetched.page + 1
        result.next_page = page

    return result


def sync_bulk_anime_seasons(
    *,
    max_pages: int = BULK_SEASON_MAX_PAGES_PER_RUN,
    max_consecutive_failures: int = BULK_SEASON_MAX_CONSECUTIVE_FAILURES,
    fetch_page: Callable[..., JikanAnimePage] = get_anime_catalogue_page,
) -> BulkSeasonSyncResult:
    """Update existing TV records while preserving the deployed TV cursor."""

    def fetch_tv_page(*, anime_type: str, page: int) -> JikanAnimePage:
        del anime_type
        return fetch_page(page=page)

    return _sync_bulk_anime_type(
        anime_type="tv",
        state_key=BULK_SEASON_STATE_KEY,
        discover_missing=False,
        max_pages=max_pages,
        max_consecutive_failures=max_consecutive_failures,
        fetch_page=fetch_tv_page,
    )


def sync_supplemental_anime_types(
    *,
    max_pages: int = BULK_SEASON_MAX_PAGES_PER_RUN,
    max_consecutive_failures: int = BULK_SEASON_MAX_CONSECUTIVE_FAILURES,
    fetch_page: Callable[..., JikanAnimePage] = get_anime_catalogue_page,
) -> SupplementalCatalogueSyncResult:
    """Discover and update OVA, ONA, Special, and TV Special catalogues."""
    scans = {}
    for anime_type in SUPPLEMENTAL_PROVIDER_TYPES:
        scans[anime_type] = _sync_bulk_anime_type(
            anime_type=anime_type,
            state_key=SUPPLEMENTAL_STATE_KEYS[anime_type],
            discover_missing=True,
            max_pages=max_pages,
            max_consecutive_failures=max_consecutive_failures,
            fetch_page=fetch_page,
        )
    return SupplementalCatalogueSyncResult(scans=scans)


def backfill_missing_seasons(
    *,
    limit: int = DEFAULT_SEASON_BACKFILL_LIMIT,
    batch_size: int = 25,
    fetch_anime: Callable[[int], dict[str, Any]] = get_anime,
) -> SeasonBackfillResult:
    """Refresh the oldest-attempted TV rows that still need a season.

    Historical season-listing endpoints can become unavailable for long
    periods even while individual anime endpoints remain usable. Every
    row is marked attempted before its request, including temporary failures,
    so repeated jobs keep advancing through the queue instead of retrying the
    same titles forever.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    with app.app_context():
        _ensure_schema()
        statement = (
            select(Anime)
            .where(
                Anime.season.is_(None),
                Anime.mal_id.is_not(None),
                Anime.mal_id > 0,
                func.upper(Anime.type) == "TV",
            )
            .options(selectinload(Anime.genre_links).selectinload(AnimeGenre.genre))
            .order_by(Anime.last_season_attempt.asc().nulls_first(), Anime.animeID)
            .limit(limit)
        )
        anime_rows = list(db.session.scalars(statement))
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
        result = SeasonBackfillResult(selected=len(anime_rows))

        for attempted, anime in enumerate(anime_rows, start=1):
            anime.last_season_attempt = datetime.now(timezone.utc)
            # A successful detail response refreshes the same fields as the
            # general catalogue queue, so keep both queues from immediately
            # requesting the same title again.
            _mark_jikan_attempt(anime)
            fetched = _fetch_anime_data(anime.mal_id, fetch_anime)
            if fetched.data is not None:
                if _is_hentai(fetched.data):
                    db.session.delete(anime)
                    result.removed_hentai += 1
                else:
                    _update_anime(anime, fetched.data, genres)
                    result.updated += 1
                    if anime.season is None:
                        result.still_missing += 1
                    else:
                        result.seasons_assigned += 1
            elif fetched.failure == "not_found":
                result.not_found += 1
            elif fetched.failure == "temporary":
                result.temporary_errors += 1
            else:
                result.invalid_payloads += 1
            _commit_completed_batch(attempted, batch_size)

        db.session.commit()
        return result


def _workflow_warning(title: str, message: str) -> None:
    if os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::warning title={title}::{message}")
    else:
        print(f"WARNING: {title}: {message}")


def _append_step_summary(title: str, rows: list[tuple[str, Any]]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with Path(summary_path).open("a", encoding="utf-8") as summary:
        summary.write(f"### {title}\n\n")
        for label, value in rows:
            summary.write(f"- **{label}:** {value}\n")
        summary.write("\n")


def _report_current_season(result: CurrentSeasonSyncResult) -> None:
    print(
        "Current season sync: "
        f"saved={result.saved}, inserted={result.inserted}, "
        f"removed_hentai={result.removed_hentai}, "
        f"seasons_assigned={result.seasons_assigned}, "
        f"pages={result.pages_completed}, failed_pages={result.pages_failed}, "
        f"complete={result.complete}, next_page={result.next_page}."
    )
    _append_step_summary(
        "Current season sync",
        [
            ("Anime saved", result.saved),
            ("Anime inserted", result.inserted),
            ("Hentai records removed", result.removed_hentai),
            ("Seasons assigned", result.seasons_assigned),
            ("Pages committed", result.pages_completed),
            ("Failed pages", result.pages_failed),
            ("Next page", result.next_page),
        ],
    )
    if result.pages_failed:
        _workflow_warning(
            "Current-season pagination paused",
            f"Page {result.next_page} failed and will be resumed by the next run.",
        )


def _report_bulk_seasons(result: BulkSeasonSyncResult) -> None:
    print(
        "Bulk anime season sync: "
        f"attempted_pages={result.pages_attempted}, "
        f"completed_pages={result.pages_completed}, "
        f"failed_pages={result.pages_failed}, updated={result.updated}, "
        f"inserted={result.inserted}, "
        f"removed_hentai={result.removed_hentai}, "
        f"seasons_assigned={result.seasons_assigned}, "
        f"complete={result.complete}, next_page={result.next_page}."
    )
    _append_step_summary(
        "Bulk anime season sync",
        [
            ("Pages attempted", result.pages_attempted),
            ("Pages completed", result.pages_completed),
            ("Pages failed", result.pages_failed),
            ("Anime updated", result.updated),
            ("Anime inserted", result.inserted),
            ("Hentai records removed", result.removed_hentai),
            ("Seasons assigned", result.seasons_assigned),
            ("Next page", result.next_page),
        ],
    )
    if result.pages_failed:
        _workflow_warning(
            "Bulk anime season sync degraded",
            f"{result.pages_failed}/{result.pages_attempted} pages failed; the next run will retry page {result.next_page}.",
        )


def _report_supplemental_catalogue(
    result: SupplementalCatalogueSyncResult,
) -> None:
    labels = {
        "ova": "OVA",
        "ona": "ONA",
        "special": "Special",
        "tv_special": "TV Special",
    }
    details = []
    for anime_type, scan in result.scans.items():
        label = labels.get(anime_type, anime_type)
        details.append(
            f"{label}: pages={scan.pages_completed}, updated={scan.updated}, "
            f"inserted={scan.inserted}, removed_hentai={scan.removed_hentai}, "
            f"failed={scan.pages_failed}, "
            f"next_page={scan.next_page}"
        )
    print(
        "Supplemental catalogue sync: "
        f"completed_pages={result.pages_completed}, "
        f"failed_pages={result.pages_failed}, updated={result.updated}, "
        f"inserted={result.inserted}, removed_hentai={result.removed_hentai}. "
        + "; ".join(details)
    )
    _append_step_summary(
        "OVA, ONA, and Special catalogue sync",
        [
            ("Pages completed", result.pages_completed),
            ("Pages failed", result.pages_failed),
            ("Anime updated", result.updated),
            ("Anime inserted", result.inserted),
            ("Hentai records removed", result.removed_hentai),
            *[
                (
                    labels.get(anime_type, anime_type),
                    (
                        f"{scan.pages_completed} pages, {scan.updated} updated, "
                        f"{scan.inserted} inserted, "
                        f"{scan.removed_hentai} Hentai removed, "
                        f"next page {scan.next_page}"
                    ),
                )
                for anime_type, scan in result.scans.items()
            ],
        ],
    )
    if result.pages_failed:
        _workflow_warning(
            "Supplemental catalogue sync degraded",
            (
                f"{result.pages_failed} OVA/ONA/Special pages failed; "
                "their independent cursors will retry those pages next run."
            ),
        )


def _report_season_backfill(result: SeasonBackfillResult) -> None:
    print(
        "TV season backfill: "
        f"selected={result.selected}, updated={result.updated}, "
        f"removed_hentai={result.removed_hentai}, "
        f"seasons_assigned={result.seasons_assigned}, "
        f"still_missing={result.still_missing}, not_found={result.not_found}, "
        f"temporary={result.temporary_errors}, invalid={result.invalid_payloads}, "
        f"success_rate={result.success_rate:.1%}."
    )
    _append_step_summary(
        "TV season backfill",
        [
            ("TV anime selected", result.selected),
            ("Anime updated", result.updated),
            ("Hentai records removed", result.removed_hentai),
            ("Seasons assigned", result.seasons_assigned),
            ("Successful responses still missing season", result.still_missing),
            ("Success rate", f"{result.success_rate:.1%}"),
            ("Temporary API failures", result.temporary_errors),
            ("Not found", result.not_found),
            ("Invalid payloads", result.invalid_payloads),
        ],
    )
    if result.selected >= 100 and result.success_rate < DEGRADED_SUCCESS_RATE:
        _workflow_warning(
            "TV season backfill degraded",
            (
                f"Only {result.updated + result.removed_hentai}/{result.selected} "
                f"records handled; {result.temporary_errors} were temporary API failures."
            ),
        )


def _report_catalogue(result: CatalogueRefreshResult) -> None:
    print(
        "Catalogue refresh: "
        f"selected={result.selected}, updated={result.updated}, "
        f"removed_hentai={result.removed_hentai}, "
        f"not_found={result.not_found}, temporary={result.temporary_errors}, "
        f"invalid={result.invalid_payloads}, missing_mal_id={result.missing_mal_id}, "
        f"success_rate={result.success_rate:.1%}."
    )
    _append_step_summary(
        "Catalogue refresh",
        [
            ("Selected", result.selected),
            ("Updated", result.updated),
            ("Hentai records removed", result.removed_hentai),
            ("Success rate", f"{result.success_rate:.1%}"),
            ("Temporary API failures", result.temporary_errors),
            ("Not found", result.not_found),
            ("Invalid payloads", result.invalid_payloads),
        ],
    )
    if result.selected >= 100 and result.success_rate < DEGRADED_SUCCESS_RATE:
        _workflow_warning(
            "Catalogue refresh degraded",
            (
                f"Only {result.updated + result.removed_hentai}/{result.selected} "
                f"records handled; {result.temporary_errors} were temporary API failures."
            ),
        )


def _report_hentai_cleanup(removed: int) -> None:
    print(f"Adult anime cleanup: removed={removed}.")
    _append_step_summary(
        "Adult-content cleanup",
        [("Hentai or Erotica anime removed", removed)],
    )


def get_season_coverage() -> SeasonCoverage:
    """Return production-facing TV season coverage for workflow reporting."""
    with app.app_context():
        total_tv = db.session.scalar(
            select(func.count(Anime.animeID)).where(func.upper(Anime.type) == "TV")
        )
        classified_tv = db.session.scalar(
            select(func.count(Anime.animeID)).where(
                func.upper(Anime.type) == "TV", Anime.season.is_not(None)
            )
        )
    return SeasonCoverage(
        total_tv=int(total_tv or 0), classified_tv=int(classified_tv or 0)
    )


def _report_catalogue_facets(total: int) -> None:
    print(f"Catalogue facets: precomputed={total}.")
    _append_step_summary(
        "Catalogue facet cache",
        [("Precomputed genre/tag options", total)],
    )


def _report_season_coverage(coverage: SeasonCoverage) -> None:
    print(
        "TV season coverage: "
        f"classified={coverage.classified_tv}, total={coverage.total_tv}, "
        f"coverage={coverage.rate:.1%}."
    )
    _append_step_summary(
        "TV season coverage",
        [
            ("TV anime with season", coverage.classified_tv),
            ("Total TV anime", coverage.total_tv),
            ("Coverage", f"{coverage.rate:.1%}"),
        ],
    )


def run_scheduled_sync(
    *,
    limit: int = DEFAULT_SEASON_BACKFILL_LIMIT,
    batch_size: int = 25,
    page_limit: int = BULK_SEASON_MAX_PAGES_PER_RUN,
) -> ScheduledSyncResult:
    """Run every scheduled phase in one process with one shared rate limiter."""
    if limit <= 0:
        raise ValueError("limit must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if page_limit <= 0:
        raise ValueError("page_limit must be positive")

    removed_hentai = remove_hentai_anime()

    current_result = sync_current_season()
    _report_current_season(current_result)

    bulk_result = sync_bulk_anime_seasons(max_pages=page_limit)
    _report_bulk_seasons(bulk_result)

    supplemental_result = sync_supplemental_anime_types(max_pages=page_limit)
    _report_supplemental_catalogue(supplemental_result)

    backfill_result = backfill_missing_seasons(limit=limit, batch_size=batch_size)
    _report_season_backfill(backfill_result)

    catalogue_result = refresh_catalogue(limit=limit, batch_size=batch_size)
    _report_catalogue(catalogue_result)

    # Preserve the established Anime pipeline even if a new readable-title
    # provider phase fails unexpectedly.
    removed_adult_manga = remove_adult_manga()
    report_manga_cleanup(removed_adult_manga)
    manga_result = sync_manga_catalogue(max_pages=page_limit)
    report_manga_catalogue(manga_result)

    manga_refresh_result = refresh_manga_catalogue(
        limit=limit, batch_size=batch_size
    )
    report_manga_refresh(manga_refresh_result)
    removed_adult_manga += (
        manga_result.removed_adult + manga_refresh_result.removed_adult
    )
    removed_hentai += (
        current_result.removed_hentai
        + bulk_result.removed_hentai
        + supplemental_result.removed_hentai
        + backfill_result.removed_hentai
        + catalogue_result.removed_hentai
    )
    _report_hentai_cleanup(removed_hentai)

    with app.app_context():
        facet_count = refresh_catalogue_facets()
    _report_catalogue_facets(facet_count)

    coverage = get_season_coverage()
    _report_season_coverage(coverage)
    return ScheduledSyncResult(
        current_season=current_result,
        bulk_seasons=bulk_result,
        supplemental_catalogue=supplemental_result,
        season_backfill=backfill_result,
        catalogue=catalogue_result,
        manga_catalogue=manga_result,
        manga_refresh=manga_refresh_result,
        coverage=coverage,
        removed_hentai=removed_hentai,
        removed_adult_manga=removed_adult_manga,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anime-id", type=int, action="append", help="Refresh only this MAL ID."
    )
    parser.add_argument(
        "--limit", type=int, help="Maximum number of catalogue rows to process."
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument(
        "--season",
        choices=("current", "winter", "spring", "summer", "fall"),
        help="Discover and save anime from this season, including sequels.",
    )
    parser.add_argument("--year", type=int, help="Year for --season (not current).")
    parser.add_argument(
        "--backfill-seasons",
        action="store_true",
        help="Fill missing TV seasons from a resumable per-anime queue.",
    )
    parser.add_argument(
        "--bulk-seasons",
        action="store_true",
        help="Update TV seasons from resumable bulk anime catalogue pages.",
    )
    parser.add_argument(
        "--scheduled-sync",
        action="store_true",
        help="Run every scheduled sync phase in one rate-limited process.",
    )
    parser.add_argument(
        "--manga-catalogue",
        action="store_true",
        help="Discover and update Manga and Manhwa catalogue pages.",
    )
    parser.add_argument(
        "--refresh-manga",
        action="store_true",
        help="Refresh the oldest-attempted Manga and Manhwa details.",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        help="Maximum bulk catalogue pages to process.",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.page_limit is not None and args.page_limit <= 0:
        parser.error("--page-limit must be positive")
    if args.year is not None and args.season in (None, "current"):
        parser.error("--year requires --season winter, spring, summer, or fall")
    if args.season and args.anime_id:
        parser.error("--anime-id cannot be combined with --season")
    if args.page_limit is not None and not (
        args.bulk_seasons or args.manga_catalogue or args.scheduled_sync
    ):
        parser.error(
            "--page-limit requires --bulk-seasons, --manga-catalogue, "
            "or --scheduled-sync"
        )
    if args.bulk_seasons and args.limit is not None:
        parser.error("--limit is not used with --bulk-seasons")
    page_limit = args.page_limit or BULK_SEASON_MAX_PAGES_PER_RUN
    if args.scheduled_sync:
        if (
            args.bulk_seasons
            or args.backfill_seasons
            or args.season
            or args.year is not None
            or args.anime_id
            or args.manga_catalogue
            or args.refresh_manga
        ):
            parser.error(
                "--scheduled-sync cannot be combined with another sync selection"
            )
        run_scheduled_sync(
            limit=args.limit or DEFAULT_SEASON_BACKFILL_LIMIT,
            batch_size=args.batch_size,
            page_limit=page_limit,
        )
    elif args.manga_catalogue:
        if (
            args.bulk_seasons
            or args.backfill_seasons
            or args.refresh_manga
            or args.season
            or args.year is not None
            or args.anime_id
        ):
            parser.error(
                "--manga-catalogue cannot be combined with another sync selection"
            )
        report_manga_catalogue(sync_manga_catalogue(max_pages=page_limit))
    elif args.refresh_manga:
        if (
            args.bulk_seasons
            or args.backfill_seasons
            or args.season
            or args.year is not None
            or args.anime_id
        ):
            parser.error(
                "--refresh-manga cannot be combined with another sync selection"
            )
        report_manga_refresh(
            refresh_manga_catalogue(
                limit=args.limit or DEFAULT_MANGA_REFRESH_LIMIT,
                batch_size=args.batch_size,
            )
        )
    elif args.bulk_seasons:
        if (
            args.backfill_seasons
            or args.season
            or args.year is not None
            or args.anime_id
        ):
            parser.error(
                "--bulk-seasons cannot be combined with anime or season selection"
            )
        _report_bulk_seasons(sync_bulk_anime_seasons(max_pages=page_limit))
    elif args.backfill_seasons:
        if args.season or args.year is not None or args.anime_id:
            parser.error(
                "--backfill-seasons cannot be combined with anime or season selection"
            )
        result = backfill_missing_seasons(
            limit=args.limit or DEFAULT_SEASON_BACKFILL_LIMIT,
            batch_size=args.batch_size,
        )
        _report_season_backfill(result)
    elif args.season == "current":
        _report_current_season(sync_current_season())
    elif args.season:
        if args.year is None:
            parser.error("a named --season requires --year")
        saved, skipped = sync_season(
            args.year,
            args.season,
            limit=args.limit,
            batch_size=args.batch_size,
        )
        print(
            f"Saved {saved} seasonal anime records; skipped {skipped} invalid records."
        )
    else:
        result = refresh_catalogue(
            args.anime_id, limit=args.limit, batch_size=args.batch_size
        )
        _report_catalogue(result)


if __name__ == "__main__":
    main()

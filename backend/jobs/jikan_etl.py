r"""Incrementally refresh PostgreSQL from Jikan-compatible anime APIs."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from backend.app import app
from backend.models import Anime, AnimeGenre, Genre, JikanSyncState, db
from backend.schema import ensure_anime_schema
from backend.services.jikan_client import (
    JikanAnimePage,
    JikanSeasonPage,
    JikanTemporaryError,
    get_anime,
    get_anime_catalogue_page,
    get_season_anime,
    get_season_page,
)


SKIPPABLE_JIKAN_STATUS_CODES = frozenset({404, 429, 500, 502, 503, 504})
TEMPORARY_JIKAN_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
JIKAN_SEASONS = frozenset({"winter", "spring", "summer", "fall"})
CURRENT_SEASON_MAX_PAGES_PER_RUN = 10
DEFAULT_SEASON_BACKFILL_LIMIT = 1000
BULK_SEASON_MAX_PAGES_PER_RUN = 40
BULK_SEASON_MAX_CONSECUTIVE_FAILURES = 3
DEGRADED_SUCCESS_RATE = 0.25


@dataclass(frozen=True)
class AnimeFetchResult:
    data: dict[str, Any] | None
    failure: str | None = None


@dataclass
class CatalogueRefreshResult:
    selected: int = 0
    updated: int = 0
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
        return self.updated / self.selected if self.selected else 0.0


@dataclass
class SeasonPageApplyResult:
    saved: int = 0
    inserted: int = 0
    skipped: int = 0
    seasons_assigned: int = 0


@dataclass
class CurrentSeasonSyncResult:
    saved: int = 0
    inserted: int = 0
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
    seasons_assigned: int = 0
    still_missing: int = 0
    not_found: int = 0
    temporary_errors: int = 0
    invalid_payloads: int = 0

    @property
    def success_rate(self) -> float:
        return self.updated / self.selected if self.selected else 0.0


@dataclass
class BulkSeasonSyncResult:
    pages_attempted: int = 0
    pages_completed: int = 0
    pages_failed: int = 0
    updated: int = 0
    seasons_assigned: int = 0
    complete: bool = False
    next_page: int = 1


def _names(entries: list[dict[str, Any]] | None) -> list[str]:
    """Return unique, non-empty Jikan category names in API order."""
    return list(
        dict.fromkeys(
            entry["name"].strip()
            for entry in entries or []
            if entry.get("name", "").strip()
        )
    )


def _detailed_genres(data: dict[str, Any], current: list[str]) -> list[str]:
    """Add Jikan genre classifications without discarding richer CSV tags."""
    jikan_names = []
    for field in ("genres", "explicit_genres", "themes", "demographics"):
        jikan_names.extend(name.lower() for name in _names(data.get(field)))
    return list(dict.fromkeys([*current, *jikan_names]))


def _valid_score(value: Any) -> float | None:
    """Return a published Jikan score; Jikan uses zero for unknown scores."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _season(value: Any) -> str | None:
    """Normalize Jikan's optional season field to supported filter values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in JIKAN_SEASONS else None


def _is_tv(anime_type: Any) -> bool:
    return isinstance(anime_type, str) and anime_type.strip().upper() == "TV"


def _update_anime(anime: Anime, data: dict[str, Any], genres: dict[str, Genre]) -> None:
    """Map one Jikan anime object onto an existing catalogue row."""
    anime.title = data.get("title") or anime.title
    anime.alternative_title = (
        data.get("title_english")
        or data.get("title_japanese")
        or anime.alternative_title
    )
    anime.type = data.get("type") or anime.type
    incoming_season = _season(data.get("season"))
    if incoming_season is not None:
        anime.season = incoming_season
    elif not _is_tv(anime.type):
        # Films and specials legitimately have no broadcast season. A sparse
        # TV response must not erase a season obtained from a seasonal listing.
        anime.season = None
    anime.year = data.get("year") or anime.year
    score = _valid_score(data.get("score"))
    if score is not None:
        anime.score = score
    anime.episodes = (
        data.get("episodes") if data.get("episodes") is not None else anime.episodes
    )
    anime.mal_url = data.get("url") or anime.mal_url

    images = data.get("images") or {}
    jpg_images = images.get("jpg") or {}
    anime.image_url = (
        jpg_images.get("large_image_url")
        or jpg_images.get("image_url")
        or anime.image_url
    )
    if "relations" in data:
        anime.sequel = any(
            relation.get("relation") == "Sequel"
            for relation in data.get("relations") or []
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

    anime.genres_detailed = _detailed_genres(data, anime.genres_detailed)
    anime.last_jikan_sync = datetime.now(timezone.utc)


def _new_anime(data: dict[str, Any]) -> Anime:
    """Create a catalogue row from a Jikan anime object."""
    images = (data.get("images") or {}).get("jpg") or {}
    mal_id = data["mal_id"]
    return Anime(
        animeID=-mal_id,
        mal_id=mal_id,
        title=data.get("title") or f"MAL anime {mal_id}",
        alternative_title=data.get("title_english") or data.get("title_japanese"),
        type=data.get("type") or "Unknown",
        season=_season(data.get("season")),
        year=data.get("year"),
        score=_valid_score(data.get("score")),
        episodes=data.get("episodes"),
        mal_url=data.get("url") or f"https://myanimelist.net/anime/{mal_id}",
        sequel=False,
        image_url=images.get("large_image_url") or images.get("image_url") or "",
        legacy_genres=[],
        genres_detailed=[],
    )


def _ensure_schema() -> None:
    ensure_anime_schema()


def _fetch_anime_data(
    mal_id: int, fetch_anime: Callable[[int], dict[str, Any]]
) -> AnimeFetchResult:
    """Fetch one record while preserving an actionable failure category."""
    try:
        payload = fetch_anime(mal_id)
    except JikanTemporaryError:
        return AnimeFetchResult(None, "temporary")
    except HTTPError as error:
        if error.code == 404:
            return AnimeFetchResult(None, "not_found")
        if error.code in TEMPORARY_JIKAN_STATUS_CODES:
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
    fetch_anime: Callable[[int], dict[str, Any]] = get_anime,
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
    seasonal_data = {
        entry["mal_id"]: _prepared_season_entry(entry, year, season)
        for entry in seasonal_entries
        if isinstance(entry.get("mal_id"), int) and entry["mal_id"] > 0
    }
    seasonal_ids = list(seasonal_data)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        seasonal_ids = seasonal_ids[:limit]

    with app.app_context():
        _ensure_schema()
        existing = {
            anime.mal_id: anime
            for anime in db.session.scalars(
                select(Anime)
                .where(Anime.mal_id.in_(seasonal_ids))
                .options(selectinload(Anime.genre_links).selectinload(AnimeGenre.genre))
            )
        }
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
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
) -> SeasonPageApplyResult:
    """Persist one page and its next-page cursor in the same transaction."""
    data_by_mal_id = {
        entry["mal_id"]: _prepared_season_entry(entry, year, season)
        for entry in page_result.entries
        if isinstance(entry.get("mal_id"), int) and entry["mal_id"] > 0
    }
    ids = list(data_by_mal_id)
    with app.app_context():
        statement = select(Anime).where(Anime.mal_id.in_(ids))
        if tv_only:
            statement = statement.where(func.upper(Anime.type) == "TV")
        statement = statement.options(
            selectinload(Anime.genre_links).selectinload(AnimeGenre.genre)
        )
        existing = {anime.mal_id: anime for anime in db.session.scalars(statement)}
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}
        result = SeasonPageApplyResult(
            skipped=len(page_result.entries) - len(data_by_mal_id)
        )

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
            if error.code not in SKIPPABLE_JIKAN_STATUS_CODES:
                raise
            resume_page = 1 if error.code == 404 and page > 1 else page
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


def sync_bulk_anime_seasons(
    *,
    max_pages: int = BULK_SEASON_MAX_PAGES_PER_RUN,
    max_consecutive_failures: int = BULK_SEASON_MAX_CONSECUTIVE_FAILURES,
    fetch_page: Callable[..., JikanAnimePage] = get_anime_catalogue_page,
) -> BulkSeasonSyncResult:
    """Update TV seasons from a low-request bulk anime catalogue.

    One successful request can update up to 25 anime. Temporary failures move
    past the failed page so a single unavailable page cannot block the whole
    catalogue. A small circuit breaker ends a run during a broad outage; the
    persisted cursor lets the next chained run continue with later pages.
    """
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if max_consecutive_failures <= 0:
        raise ValueError("max_consecutive_failures must be positive")

    state_key = "bulk:anime-catalogue-seasons"
    with app.app_context():
        _ensure_schema()
    page = _next_page(state_key)
    result = BulkSeasonSyncResult(next_page=page)
    consecutive_failures = 0

    for _ in range(max_pages):
        result.pages_attempted += 1
        try:
            fetched = fetch_page(page=page)
        except JikanTemporaryError as error:
            page += 1
            _record_page_error(state_key, page, error)
            result.pages_failed += 1
            result.next_page = page
            consecutive_failures += 1
            if consecutive_failures >= max_consecutive_failures:
                break
            continue
        except HTTPError as error:
            if error.code not in SKIPPABLE_JIKAN_STATUS_CODES:
                raise
            if error.code == 404 and page > 1:
                _record_page_error(state_key, 1, error)
                result.pages_failed += 1
                result.complete = True
                result.next_page = 1
                break
            page += 1
            _record_page_error(state_key, page, error)
            result.pages_failed += 1
            result.next_page = page
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
            discover_missing=False,
            tv_only=True,
        )
        result.pages_completed += 1
        result.updated += applied.saved
        result.seasons_assigned += applied.seasons_assigned
        if not fetched.has_next_page:
            result.complete = True
            result.next_page = 1
            break
        page = fetched.page + 1
        result.next_page = page

    return result


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
        "--page-limit",
        type=int,
        default=BULK_SEASON_MAX_PAGES_PER_RUN,
        help="Maximum bulk catalogue pages to process.",
    )
    args = parser.parse_args()

    if args.year is not None and args.season in (None, "current"):
        parser.error("--year requires --season winter, spring, summer, or fall")
    if args.bulk_seasons:
        if (
            args.backfill_seasons
            or args.season
            or args.year is not None
            or args.anime_id
        ):
            parser.error(
                "--bulk-seasons cannot be combined with anime or season selection"
            )
        result = sync_bulk_anime_seasons(max_pages=args.page_limit)
        print(
            "Bulk anime season sync: "
            f"attempted_pages={result.pages_attempted}, "
            f"completed_pages={result.pages_completed}, "
            f"failed_pages={result.pages_failed}, updated={result.updated}, "
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
                ("Seasons assigned", result.seasons_assigned),
                ("Next page", result.next_page),
            ],
        )
        if result.pages_failed:
            _workflow_warning(
                "Bulk anime season sync degraded",
                f"{result.pages_failed}/{result.pages_attempted} pages failed; the next run will continue at page {result.next_page}.",
            )
    elif args.backfill_seasons:
        if args.season or args.year is not None or args.anime_id:
            parser.error(
                "--backfill-seasons cannot be combined with anime or season selection"
            )
        result = backfill_missing_seasons(
            limit=args.limit or DEFAULT_SEASON_BACKFILL_LIMIT,
            batch_size=args.batch_size,
        )
        print(
            "TV season backfill: "
            f"selected={result.selected}, updated={result.updated}, "
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
                f"Only {result.updated}/{result.selected} records updated; {result.temporary_errors} were temporary API failures.",
            )
    elif args.season == "current":
        result = sync_current_season()
        print(
            "Current season sync: "
            f"saved={result.saved}, inserted={result.inserted}, "
            f"seasons_assigned={result.seasons_assigned}, "
            f"pages={result.pages_completed}, failed_pages={result.pages_failed}, "
            f"complete={result.complete}, next_page={result.next_page}."
        )
        _append_step_summary(
            "Current season sync",
            [
                ("Anime saved", result.saved),
                ("Anime inserted", result.inserted),
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
        print(
            "Catalogue refresh: "
            f"selected={result.selected}, updated={result.updated}, "
            f"not_found={result.not_found}, temporary={result.temporary_errors}, "
            f"invalid={result.invalid_payloads}, missing_mal_id={result.missing_mal_id}, "
            f"success_rate={result.success_rate:.1%}."
        )
        _append_step_summary(
            "Catalogue refresh",
            [
                ("Selected", result.selected),
                ("Updated", result.updated),
                ("Success rate", f"{result.success_rate:.1%}"),
                ("Temporary API failures", result.temporary_errors),
                ("Not found", result.not_found),
                ("Invalid payloads", result.invalid_payloads),
            ],
        )
        if result.selected >= 100 and result.success_rate < DEGRADED_SUCCESS_RATE:
            _workflow_warning(
                "Catalogue refresh degraded",
                f"Only {result.updated}/{result.selected} records updated; {result.temporary_errors} were temporary API failures.",
            )


if __name__ == "__main__":
    main()

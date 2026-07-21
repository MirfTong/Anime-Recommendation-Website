r"""Refresh the existing anime catalogue from Jikan's full-anime endpoint.

Run a small trial first:

    .\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --anime-id 1

Run the full catalogue only when ready (it is intentionally rate-limited):

    .\.venv\Scripts\python.exe -m backend.jobs.jikan_etl
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from backend.app import app
from backend.models import Anime, AnimeGenre, Genre, db
from backend.schema import ensure_anime_schema
from backend.services.jikan_client import (
    JikanTemporaryError,
    get_anime_full,
    get_season_anime,
)


SKIPPABLE_JIKAN_STATUS_CODES = frozenset({404, 500, 502, 503, 504})
JIKAN_SEASONS = frozenset({"winter", "spring", "summer", "fall"})


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
    """Return a published Jikan score; Jikan uses zero for an unknown score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


def _season(value: Any) -> str | None:
    """Normalize Jikan's optional season field to the supported filter values."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in JIKAN_SEASONS else None


def _update_anime(anime: Anime, data: dict[str, Any], genres: dict[str, Genre]) -> None:
    """Map a Jikan ``data`` object onto one existing ``Anime`` row."""
    anime.title = data.get("title") or anime.title
    anime.alternative_title = (
        data.get("title_english")
        or data.get("title_japanese")
        or anime.alternative_title
    )
    anime.type = data.get("type") or anime.type
    # Clear stale values when Jikan has no seasonal classification, such as
    # for films and specials.
    anime.season = _season(data.get("season"))
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
    """Create a row from Jikan data, including safe values for sparse records."""
    images = (data.get("images") or {}).get("jpg") or {}
    mal_id = data["mal_id"]
    return Anime(
        # Dataset row IDs are positive. Negative IDs keep seasonal additions
        # distinct without colliding with rows imported from the CSV.
        animeID=-mal_id,
        mal_id=mal_id,
        title=data.get("title") or f"MAL anime {data['mal_id']}",
        alternative_title=data.get("title_english") or data.get("title_japanese"),
        type=data.get("type") or "Unknown",
        season=_season(data.get("season")),
        year=data.get("year"),
        score=_valid_score(data.get("score")),
        episodes=data.get("episodes"),
        mal_url=data.get("url") or f"https://myanimelist.net/anime/{data['mal_id']}",
        sequel=False,
        image_url=images.get("large_image_url") or images.get("image_url") or "",
        legacy_genres=[],
        genres_detailed=[],
    )


def _ensure_schema() -> None:
    """Apply the shared schema setup before an ETL run."""
    ensure_anime_schema()


def _fetch_anime_data(
    mal_id: int, fetch_anime: Callable[[int], dict[str, Any]]
) -> dict[str, Any] | None:
    """Fetch one Jikan anime record, returning ``None`` for skippable failures."""
    try:
        payload = fetch_anime(mal_id)
    except JikanTemporaryError:
        return None
    except HTTPError as error:
        if error.code not in SKIPPABLE_JIKAN_STATUS_CODES:
            db.session.rollback()
            raise
        return None

    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _commit_completed_batch(processed_count: int, batch_size: int) -> None:
    """Commit each completed batch of processed catalogue records."""
    if processed_count % batch_size == 0:
        db.session.commit()


def _mark_jikan_attempt(anime: Anime) -> None:
    """Record an ETL attempt without adding a web-app model dependency."""
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
) -> tuple[int, int]:
    """Fetch and update existing anime rows; return ``(updated, skipped)``.

    Every selected record is marked as attempted, including missing records and
    temporary Jikan failures. This lets the oldest-first queue continue past
    unavailable records while ``last_jikan_sync`` remains success-only.
    """
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
            statement = statement.where(Anime.animeID.in_(list(anime_ids)))
        if anime_ids is None:
            statement = statement.order_by(
                text("last_jikan_attempt ASC NULLS FIRST"), Anime.animeID
            )
        else:
            statement = statement.order_by(Anime.animeID)
        if limit is not None:
            statement = statement.limit(limit)
        anime_rows = list(db.session.scalars(statement))
        genres = {genre.name: genre for genre in db.session.scalars(select(Genre))}

        updated = skipped = attempted = 0
        for anime in anime_rows:
            _mark_jikan_attempt(anime)
            if anime.mal_id is None:
                skipped += 1
            else:
                data = _fetch_anime_data(anime.mal_id, fetch_anime)
                if data is None:
                    skipped += 1
                else:
                    _update_anime(anime, data, genres)
                    updated += 1

            attempted += 1
            _commit_completed_batch(attempted, batch_size)

        db.session.commit()
        return updated, skipped


def sync_season(
    year: int | None = None,
    season: str | None = None,
    *,
    limit: int | None = None,
    batch_size: int = 25,
    fetch_anime: Callable[[int], dict[str, Any]] = get_anime_full,
    fetch_season: Callable[[int | None, str | None], list[dict[str, Any]]] = get_season_anime,
) -> tuple[int, int]:
    """Discover a season's anime and insert or update them; return ``(saved, skipped)``."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    seasonal_ids = list(
        dict.fromkeys(
            entry["mal_id"]
            for entry in fetch_season(year, season)
            if isinstance(entry.get("mal_id"), int) and entry["mal_id"] > 0
        )
    )
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
        saved = skipped = 0
        for mal_id in seasonal_ids:
            data = _fetch_anime_data(mal_id, fetch_anime)
            if data is None:
                skipped += 1
                continue
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--anime-id", type=int, action="append", help="Refresh only this MAL ID."
    )
    parser.add_argument("--limit", type=int, help="Maximum number of rows to refresh.")
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument(
        "--season",
        choices=("current", "winter", "spring", "summer", "fall"),
        help="Discover and save anime from this season, including sequels.",
    )
    parser.add_argument("--year", type=int, help="Year for --season (not current).")
    args = parser.parse_args()

    if args.year is not None and args.season in (None, "current"):
        parser.error("--year requires --season winter, spring, summer, or fall")
    if args.season:
        year = None if args.season == "current" else args.year
        if args.season != "current" and year is None:
            parser.error("a named --season requires --year")
        saved, skipped = sync_season(
            year, None if args.season == "current" else args.season,
            limit=args.limit, batch_size=args.batch_size,
        )
        print(f"Saved {saved} seasonal anime records; skipped {skipped} missing Jikan records.")
    else:
        updated, skipped = refresh_catalogue(
            args.anime_id, limit=args.limit, batch_size=args.batch_size
        )
        print(f"Updated {updated} anime records; skipped {skipped} missing Jikan records.")


if __name__ == "__main__":
    main()

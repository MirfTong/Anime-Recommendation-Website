"""Flask REST API and single-service React application host."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.orm import selectinload

from backend.models import Anime, CatalogueFacet, Genre, Manga, db
from backend.schema import ensure_anime_schema


load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

API_PREFIX = "/api/v1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_BUILD_DIR = PROJECT_ROOT / "static" / "react"
MAX_PAGE_SIZE = 100
MAX_TAG_OPTIONS = 100
VALID_SEASONS = frozenset({"winter", "spring", "summer", "fall"})
VALID_ANIME_STATUSES = frozenset(
    {"CURRENTLY_AIRING", "FINISHED_AIRING", "NOT_YET_AIRED"}
)
ANIME_STATUS_ALIASES = {
    "AIRING": "CURRENTLY_AIRING",
    "CURRENTLY_AIRING": "CURRENTLY_AIRING",
    "FINISHED": "FINISHED_AIRING",
    "FINISHED_AIRING": "FINISHED_AIRING",
    "NOT_YET_AIRED": "NOT_YET_AIRED",
    "NOT_YET_AIRING": "NOT_YET_AIRED",
}
COMMON_SORTS = frozenset({"top_rated", "newest", "oldest", "title"})
ANIME_SORTS = COMMON_SORTS | {"most_episodes"}
PRINT_SORTS = COMMON_SORTS | {"most_chapters"}
TYPE_ALIASES = {"TV SPECIAL": "SPECIAL"}
CONTENT_TYPE_SCOPES = {
    "ANIME": frozenset({"ANIME"}),
    "MANGA": frozenset({"MANGA"}),
    "MANHWA": frozenset({"MANHWA"}),
    "ALL": frozenset({"ANIME", "MANGA", "MANHWA"}),
}
CACHE_TTL_SECONDS = 300


class TtlCache:
    """Small process-local cache for repeatable catalogue metadata queries."""

    def __init__(self) -> None:
        self._values: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._lock = Lock()

    def get_or_create(self, key: tuple[Any, ...], factory):
        now = monotonic()
        with self._lock:
            cached = self._values.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]

        value = factory()
        with self._lock:
            self._values[key] = (now + CACHE_TTL_SECONDS, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()


response_cache = TtlCache()


@dataclass(frozen=True)
class CommonFilters:
    query: str
    min_score: float | None
    min_year: int | None
    max_year: int | None
    genres: tuple[str, ...]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class AnimeFilters:
    min_episodes: int | None
    max_episodes: int | None
    anime_types: tuple[str, ...]
    seasons: tuple[str, ...]
    statuses: tuple[str, ...]

    @property
    def active(self) -> bool:
        return bool(
            self.min_episodes
            or self.max_episodes
            or self.anime_types
            or self.seasons
            or self.statuses
        )


@dataclass(frozen=True)
class MangaFilters:
    statuses: tuple[str, ...]
    min_chapters: int | None
    min_volumes: int | None

    @property
    def active(self) -> bool:
        return bool(self.statuses or self.min_chapters or self.min_volumes)


def _current_season_identity(now: datetime | None = None) -> tuple[int, str]:
    """Return the current anime season using Japan's calendar."""
    japan_time = timezone(timedelta(hours=9))
    current = (now or datetime.now(timezone.utc)).astimezone(japan_time)
    seasons = ("winter", "spring", "summer", "fall")
    return current.year, seasons[(current.month - 1) // 3]


class ApiError(Exception):
    """A validation error that should be returned as JSON."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code


@app.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return jsonify({"error": {"message": error.message}}), error.status_code


@app.errorhandler(404)
def handle_not_found(_error):
    if request.path.startswith(API_PREFIX):
        return jsonify({"error": {"message": "Resource not found"}}), 404
    return _error


def _integer_argument(name: str, *, minimum: int, maximum: int | None = None) -> int | None:
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise ApiError(f"{name} must be an integer") from error
    if parsed < minimum or (maximum is not None and parsed > maximum):
        limit = f" between {minimum} and {maximum}" if maximum is not None else f" at least {minimum}"
        raise ApiError(f"{name} must be{limit}")
    return parsed


def _float_argument(name: str, *, minimum: float, maximum: float) -> float | None:
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as error:
        raise ApiError(f"{name} must be a number") from error
    if not minimum <= parsed <= maximum:
        raise ApiError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _list_argument(name: str) -> list[str]:
    """Read repeatable and comma-separated filter parameters."""
    values = []
    for raw_value in request.args.getlist(name):
        values.extend(value.strip() for value in raw_value.split(",") if value.strip())
    return list(dict.fromkeys(values))


def _request_filter_signature(*, exclude: set[str]) -> tuple[Any, ...]:
    return tuple(
        sorted(
            (
                key,
                tuple(request.args.getlist(key)),
            )
            for key in request.args
            if key not in exclude
        )
    )


def _cached_scalar_count(key: tuple[Any, ...], statement) -> int:
    return response_cache.get_or_create(
        key,
        lambda: int(db.session.scalar(statement) or 0),
    )


def _normalized_type(value: str) -> str:
    """Match filter input to the canonical uppercase database type."""
    normalized = " ".join(value.replace("_", " ").split()).upper()
    return TYPE_ALIASES.get(normalized, normalized)


def _normalized_content_type(value: str, *, allow_all: bool = True) -> str:
    normalized = value.strip().upper()
    valid_types = CONTENT_TYPE_SCOPES if allow_all else {
        key: scope for key, scope in CONTENT_TYPE_SCOPES.items() if key != "ALL"
    }
    if normalized not in valid_types:
        choices = "ANIME, MANGA, MANHWA, or ALL" if allow_all else (
            "ANIME, MANGA, or MANHWA"
        )
        raise ApiError(f"content_type must be {choices}")
    return normalized


def _content_type_argument(*, default: str) -> str:
    value = request.args.get("content_type")
    if value is None or not value.strip():
        return default
    return _normalized_content_type(value)


def _sort_argument(content_types: frozenset[str] | set[str]) -> str:
    """Validate sorting against the selected media scope."""
    sort = request.args.get("sort", "top_rated").strip().lower()
    normalized_types = frozenset(content_types)
    if normalized_types == frozenset({"ANIME"}):
        valid_sorts = ANIME_SORTS
    elif normalized_types.issubset({"MANGA", "MANHWA"}):
        valid_sorts = PRINT_SORTS
    else:
        valid_sorts = COMMON_SORTS
    if sort not in valid_sorts:
        raise ApiError(
            "sort must be " + ", ".join(sorted(valid_sorts))
        )
    return sort


def _normalized_status(value: str) -> str:
    """Normalize UI constants such as NOT_YET_PUBLISHED to provider labels."""
    return " ".join(value.replace("_", " ").split()).casefold()


def _normalized_anime_status(value: str) -> str:
    normalized = "_".join(value.replace("-", " ").split()).upper()
    status = ANIME_STATUS_ALIASES.get(normalized)
    if status is None:
        raise ApiError(
            "anime status must be CURRENTLY_AIRING, FINISHED_AIRING, "
            "or NOT_YET_AIRED"
        )
    return status


def _escaped_search_pattern(query: str) -> str:
    escaped = (
        query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


def _common_filter_values() -> CommonFilters:
    min_year = _integer_argument("min_year", minimum=1, maximum=3000)
    max_year = _integer_argument("max_year", minimum=1, maximum=3000)
    if min_year is not None and max_year is not None and min_year > max_year:
        raise ApiError("min_year cannot be greater than max_year")
    return CommonFilters(
        query=request.args.get("q", "").strip(),
        min_score=_float_argument("min_score", minimum=0, maximum=10),
        min_year=min_year,
        max_year=max_year,
        genres=tuple(_list_argument("genre")),
        tags=tuple(_list_argument("tag")),
    )


def _anime_filter_values(*, include_status: bool = True) -> AnimeFilters:
    seasons = tuple(season.lower() for season in _list_argument("season"))
    invalid_seasons = set(seasons).difference(VALID_SEASONS)
    if invalid_seasons:
        raise ApiError("season must be winter, spring, summer, or fall")
    min_episodes = _integer_argument(
        "min_episodes", minimum=1, maximum=10000
    )
    max_episodes = _integer_argument(
        "max_episodes", minimum=1, maximum=10000
    )
    if (
        min_episodes is not None
        and max_episodes is not None
        and min_episodes > max_episodes
    ):
        raise ApiError("min_episodes cannot be greater than max_episodes")
    return AnimeFilters(
        min_episodes=min_episodes,
        max_episodes=max_episodes,
        anime_types=tuple(
            _normalized_type(value) for value in _list_argument("type")
        ),
        seasons=seasons,
        statuses=(
            tuple(
                _normalized_anime_status(value)
                for value in _list_argument("status")
            )
            if include_status
            else ()
        ),
    )


def _manga_filter_values(*, include_status: bool = True) -> MangaFilters:
    return MangaFilters(
        statuses=(
            tuple(
                _normalized_status(value)
                for value in _list_argument("status")
            )
            if include_status
            else ()
        ),
        min_chapters=_integer_argument(
            "min_chapters", minimum=1, maximum=1_000_000
        ),
        min_volumes=_integer_argument(
            "min_volumes", minimum=1, maximum=100_000
        ),
    )


def _serialize_anime(anime: Anime, *, detailed: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": anime.animeID,
        "mal_id": anime.mal_id,
        "content_type": "ANIME",
        "title": anime.title,
        "alternative_title": anime.alternative_title,
        "type": anime.type,
        "season": anime.season,
        "status": anime.status,
        "year": anime.year,
        "score": anime.score,
        "episodes": anime.episodes,
        "image_url": anime.image_url,
        "mal_url": anime.mal_url,
        "sequel": anime.sequel,
        "genres": [genre.name for genre in anime.genre_entries],
    }
    if detailed:
        payload["synopsis"] = anime.synopsis
        payload["genres_detailed"] = anime.genres_detailed
        payload["last_jikan_sync"] = (
            anime.last_jikan_sync.isoformat() if anime.last_jikan_sync else None
        )
    return payload


def _serialize_manga(manga: Manga, *, detailed: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": manga.mangaID,
        "mal_id": manga.mal_id,
        "content_type": manga.content_type,
        "title": manga.title,
        "alternative_title": manga.alternative_title,
        "type": manga.manga_type,
        "manga_type": manga.manga_type,
        "status": manga.status,
        "year": manga.publication_year,
        "publication_year": manga.publication_year,
        "score": manga.score,
        "chapters": manga.chapters,
        "volumes": manga.volumes,
        "image_url": manga.image_url,
        "mal_url": manga.mal_url,
        "genres": [genre.name for genre in manga.genre_entries],
    }
    if detailed:
        payload["synopsis"] = manga.synopsis
        payload["genres_detailed"] = manga.genres_detailed or []
        payload["last_jikan_sync"] = (
            manga.last_jikan_sync.isoformat() if manga.last_jikan_sync else None
        )
    return payload


def _public_statement(model):
    """Return the indexed, ETL-maintained public catalogue query."""
    return (
        select(model)
        .where(model.is_adult.is_(False))
        .options(selectinload(model.genre_entries))
    )


def _anime_statement():
    """Base public anime query."""
    return _public_statement(Anime)


def _manga_statement(
    content_types: frozenset[str] | set[str] | None = None,
):
    """Base public Manga/Manhwa query."""
    statement = _public_statement(Manga)
    if content_types is not None:
        statement = statement.where(
            Manga.content_type.in_(sorted(content_types))
        )
    return statement


def _apply_common_filters(
    statement,
    model,
    year_column,
    filters: CommonFilters,
):
    if filters.query:
        pattern = _escaped_search_pattern(filters.query)
        statement = statement.where(
            or_(
                model.title.ilike(pattern, escape="\\"),
                model.alternative_title.ilike(pattern, escape="\\"),
            )
        )
    if filters.min_score is not None:
        statement = statement.where(model.score >= filters.min_score)
    if filters.min_year is not None:
        statement = statement.where(year_column >= filters.min_year)
    if filters.max_year is not None:
        statement = statement.where(year_column <= filters.max_year)
    for genre in filters.genres:
        statement = statement.where(
            model.genre_entries.any(Genre.name == genre)
        )
    for tag in filters.tags:
        statement = statement.where(model.genres_detailed.contains([tag]))
    return statement


def _filtered_anime_statement(
    common_filters: CommonFilters | None = None,
    anime_filters: AnimeFilters | None = None,
):
    common_filters = common_filters or _common_filter_values()
    anime_filters = anime_filters or _anime_filter_values()
    statement = _apply_common_filters(
        _anime_statement(), Anime, Anime.year, common_filters
    )
    if anime_filters.min_episodes is not None:
        statement = statement.where(
            Anime.episodes >= anime_filters.min_episodes
        )
    if anime_filters.max_episodes is not None:
        statement = statement.where(
            Anime.episodes <= anime_filters.max_episodes
        )
    if anime_filters.anime_types:
        statement = statement.where(
            Anime.type.in_(anime_filters.anime_types)
        )
    if anime_filters.seasons:
        statement = statement.where(Anime.season.in_(anime_filters.seasons))
    if anime_filters.statuses:
        statement = statement.where(Anime.status.in_(anime_filters.statuses))
    return statement


def _filtered_manga_statement(
    content_types: frozenset[str] | set[str],
    common_filters: CommonFilters | None = None,
    manga_filters: MangaFilters | None = None,
):
    common_filters = common_filters or _common_filter_values()
    manga_filters = manga_filters or _manga_filter_values()
    statement = _apply_common_filters(
        _manga_statement(content_types),
        Manga,
        Manga.publication_year,
        common_filters,
    )
    if manga_filters.statuses:
        statement = statement.where(
            func.lower(func.trim(Manga.status)).in_(
                manga_filters.statuses
            )
        )
    if manga_filters.min_chapters is not None:
        statement = statement.where(
            Manga.chapters >= manga_filters.min_chapters
        )
    if manga_filters.min_volumes is not None:
        statement = statement.where(
            Manga.volumes >= manga_filters.min_volumes
        )
    return statement


def _catalogue_rows_subquery(
    content_types: frozenset[str] | set[str],
):
    """Build one normalized identity stream for deterministic mixed paging."""
    common_filters = _common_filter_values()
    effective_types = set(content_types)
    includes_anime = "ANIME" in effective_types
    includes_print = bool(
        effective_types.intersection({"MANGA", "MANHWA"})
    )
    if includes_anime and includes_print and _list_argument("status"):
        raise ApiError(
            "status cannot be shared across mixed content; select Anime, "
            "Manga, or Manhwa first"
        )
    anime_filters = _anime_filter_values(include_status=not includes_print)
    manga_filters = _manga_filter_values(include_status=not includes_anime)

    # A medium-specific filter cannot sensibly match rows from the other
    # medium. This also makes such filters useful when content_type=ALL.
    if anime_filters.active:
        effective_types.intersection_update({"ANIME"})
    if manga_filters.active:
        effective_types.difference_update({"ANIME"})

    branches = []
    if "ANIME" in effective_types:
        anime_rows = (
            _filtered_anime_statement(common_filters, anime_filters)
            .order_by(None)
            .subquery("filtered_anime")
        )
        branches.append(
            select(
                literal("ANIME").label("content_type"),
                anime_rows.c.anime_id.label("record_id"),
                anime_rows.c.mal_id.label("mal_id"),
                anime_rows.c.score.label("score"),
                anime_rows.c.title.label("title"),
                anime_rows.c.year.label("year"),
                anime_rows.c.episodes.label("length"),
            )
        )

    manga_content_types = effective_types.intersection({"MANGA", "MANHWA"})
    if manga_content_types:
        manga_rows = (
            _filtered_manga_statement(
                manga_content_types, common_filters, manga_filters
            )
            .order_by(None)
            .subquery("filtered_manga")
        )
        branches.append(
            select(
                manga_rows.c.content_type.label("content_type"),
                manga_rows.c.manga_id.label("record_id"),
                manga_rows.c.mal_id.label("mal_id"),
                manga_rows.c.score.label("score"),
                manga_rows.c.title.label("title"),
                manga_rows.c.publication_year.label("year"),
                manga_rows.c.chapters.label("length"),
            )
        )

    if not branches:
        return None
    combined = branches[0] if len(branches) == 1 else union_all(*branches)
    return combined.subquery("catalogue_rows")


def _ordered_catalogue_rows(catalogue_rows, sort: str):
    statement = select(
        catalogue_rows.c.content_type,
        catalogue_rows.c.record_id,
        catalogue_rows.c.mal_id,
        catalogue_rows.c.score,
        catalogue_rows.c.title,
    )
    score_order = catalogue_rows.c.score.desc().nullslast()
    title_order = (
        func.lower(catalogue_rows.c.title),
        catalogue_rows.c.title,
    )
    if sort == "newest":
        primary_order = (
            catalogue_rows.c.year.desc().nullslast(),
            score_order,
            *title_order,
        )
    elif sort == "oldest":
        primary_order = (
            catalogue_rows.c.year.asc().nullslast(),
            score_order,
            *title_order,
        )
    elif sort == "title":
        primary_order = (*title_order, score_order)
    elif sort in {"most_episodes", "most_chapters"}:
        primary_order = (
            catalogue_rows.c.length.desc().nullslast(),
            score_order,
            *title_order,
        )
    else:
        primary_order = (score_order, *title_order)
    return statement.order_by(
        *primary_order,
        catalogue_rows.c.content_type,
        catalogue_rows.c.mal_id.nulls_last(),
        catalogue_rows.c.record_id,
    )


def _catalogue_freshness(
    content_types: frozenset[str] | set[str],
) -> str | None:
    """Return a cached latest successful ETL timestamp for this scope."""
    normalized_types = frozenset(content_types)

    def load_freshness() -> str | None:
        timestamps = []
        if "ANIME" in normalized_types:
            anime_timestamp = db.session.scalar(
                select(func.max(Anime.last_jikan_sync)).where(
                    Anime.is_adult.is_(False)
                )
            )
            if anime_timestamp is not None:
                timestamps.append(anime_timestamp)
        if normalized_types.intersection({"MANGA", "MANHWA"}):
            manga_timestamp = db.session.scalar(
                select(func.max(Manga.last_jikan_sync)).where(
                    Manga.is_adult.is_(False),
                    Manga.content_type.in_(
                        sorted(
                            normalized_types.intersection(
                                {"MANGA", "MANHWA"}
                            )
                        )
                    ),
                )
            )
            if manga_timestamp is not None:
                timestamps.append(manga_timestamp)
        if not timestamps:
            return None

        def comparable(timestamp: datetime) -> datetime:
            return (
                timestamp.replace(tzinfo=timezone.utc)
                if timestamp.tzinfo is None
                else timestamp.astimezone(timezone.utc)
            )

        return max(timestamps, key=comparable).isoformat()

    return response_cache.get_or_create(
        ("catalogue-freshness", tuple(sorted(normalized_types))),
        load_freshness,
    )


def _serialize_catalogue_rows(rows) -> list[dict[str, Any]]:
    """Hydrate normalized identity rows without losing their global order."""
    anime_ids = [
        row.record_id for row in rows if row.content_type == "ANIME"
    ]
    manga_ids = [
        row.record_id for row in rows if row.content_type != "ANIME"
    ]
    entries_by_key: dict[tuple[str, int], Anime | Manga] = {}

    if anime_ids:
        anime = db.session.scalars(
            _anime_statement().where(Anime.animeID.in_(anime_ids))
        ).all()
        entries_by_key.update(
            {("ANIME", entry.animeID): entry for entry in anime}
        )
    if manga_ids:
        manga = db.session.scalars(
            _manga_statement().where(Manga.mangaID.in_(manga_ids))
        ).all()
        entries_by_key.update(
            {
                (entry.content_type, entry.mangaID): entry
                for entry in manga
            }
        )

    items = []
    for row in rows:
        entry = entries_by_key.get((row.content_type, row.record_id))
        if isinstance(entry, Anime):
            items.append(_serialize_anime(entry))
        elif isinstance(entry, Manga):
            items.append(_serialize_manga(entry))
    return items


def _ordered_anime_statement(statement, sort: str):
    """Apply the same deterministic sort contract to the anime alias route."""
    score_order = Anime.score.desc().nullslast()
    title_order = (func.lower(Anime.title), Anime.title)
    if sort == "newest":
        order = (Anime.year.desc().nullslast(), score_order, *title_order)
    elif sort == "oldest":
        order = (Anime.year.asc().nullslast(), score_order, *title_order)
    elif sort == "title":
        order = (*title_order, score_order)
    elif sort == "most_episodes":
        order = (
            Anime.episodes.desc().nullslast(),
            score_order,
            *title_order,
        )
    else:
        order = (score_order, *title_order)
    return statement.order_by(*order, Anime.mal_id.nulls_last(), Anime.animeID)


def _list_catalogue(content_types: frozenset[str] | set[str]):
    page = _integer_argument("page", minimum=1) or 1
    per_page = (
        _integer_argument(
            "per_page", minimum=1, maximum=MAX_PAGE_SIZE
        )
        or 24
    )
    sort = _sort_argument(content_types)
    catalogue_rows = _catalogue_rows_subquery(content_types)
    if catalogue_rows is None:
        total = 0
        items = []
    else:
        count_key = (
            "catalogue-total",
            tuple(sorted(content_types)),
            _request_filter_signature(
                exclude={"content_type", "page", "per_page", "sort"}
            ),
        )
        total = _cached_scalar_count(
            count_key,
            select(func.count()).select_from(catalogue_rows),
        )
        rows = db.session.execute(
            _ordered_catalogue_rows(catalogue_rows, sort)
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).all()
        items = _serialize_catalogue_rows(rows)
    return jsonify(
        {
            "items": items,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
            "updated_at": _catalogue_freshness(content_types),
        }
    )


def _random_catalogue(content_types: frozenset[str] | set[str]):
    limit = _integer_argument("limit", minimum=1, maximum=12) or 6
    catalogue_rows = _catalogue_rows_subquery(content_types)
    if catalogue_rows is None:
        return jsonify({"items": []})
    rows = db.session.execute(
        select(
            catalogue_rows.c.content_type,
            catalogue_rows.c.record_id,
            catalogue_rows.c.mal_id,
            catalogue_rows.c.score,
            catalogue_rows.c.title,
        )
        .order_by(func.random())
        .limit(limit)
    ).all()
    return jsonify({"items": _serialize_catalogue_rows(rows)})


def _catalogue_detail_response(content_type: str, mal_id: int):
    normalized_type = _normalized_content_type(
        content_type, allow_all=False
    )
    if normalized_type == "ANIME":
        entry = db.session.scalar(
            _anime_statement().where(Anime.mal_id == mal_id)
        )
        if entry is None:
            raise ApiError("Anime not found", 404)
        return jsonify({"item": _serialize_anime(entry, detailed=True)})

    entry = db.session.scalar(
        _manga_statement({normalized_type}).where(Manga.mal_id == mal_id)
    )
    if entry is None:
        label = "Manga" if normalized_type == "MANGA" else "Manhwa"
        raise ApiError(f"{label} not found", 404)
    return jsonify({"item": _serialize_manga(entry, detailed=True)})


@app.get(f"{API_PREFIX}/anime")
def list_anime():
    """Search, filter, and deterministically sort anime."""
    page = _integer_argument("page", minimum=1) or 1
    per_page = _integer_argument("per_page", minimum=1, maximum=MAX_PAGE_SIZE) or 24
    sort = _sort_argument(CONTENT_TYPE_SCOPES["ANIME"])
    statement = _filtered_anime_statement()
    total = _cached_scalar_count(
        (
            "anime-total",
            _request_filter_signature(exclude={"page", "per_page", "sort"}),
        ),
        select(func.count()).select_from(statement.order_by(None).subquery()),
    )
    items = db.session.scalars(
        _ordered_anime_statement(statement, sort)
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()
    return jsonify(
        {
            "items": [_serialize_anime(anime) for anime in items],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "pages": (total + per_page - 1) // per_page,
            },
            "updated_at": _catalogue_freshness(
                CONTENT_TYPE_SCOPES["ANIME"]
            ),
        }
    )


@app.get(f"{API_PREFIX}/anime/random")
def random_anime():
    """Return a small random selection of public anime."""
    limit = _integer_argument("limit", minimum=1, maximum=12) or 6
    anime = db.session.scalars(
        _anime_statement()
        .order_by(func.random())
        .limit(limit)
    ).all()
    return jsonify({"items": [_serialize_anime(entry) for entry in anime]})


@app.get(f"{API_PREFIX}/anime/seasonal")
def popular_current_season():
    """Return the highest-rated anime from the current Japan-season window."""
    limit = _integer_argument("limit", minimum=1, maximum=12) or 6
    page = _integer_argument("page", minimum=1) or 1
    year, season = _current_season_identity()
    filters = (
        Anime.score.is_not(None),
        Anime.year == year,
        Anime.season == season,
    )
    public_season = _anime_statement().where(*filters).order_by(None).subquery()
    total = _cached_scalar_count(
        ("seasonal-total", year, season),
        select(func.count()).select_from(public_season),
    )
    anime = db.session.scalars(
        _anime_statement()
        .where(*filters)
        .order_by(Anime.score.desc(), Anime.title)
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    return jsonify(
        {
            "items": [_serialize_anime(entry) for entry in anime],
            "season": season,
            "year": year,
            "pagination": {
                "page": page,
                "per_page": limit,
                "total": total,
                "pages": (total + limit - 1) // limit,
            },
        }
    )


@app.get(f"{API_PREFIX}/anime/<int:mal_id>")
def anime_detail(mal_id: int):
    """Return the full record for one MyAnimeList anime ID."""
    anime = db.session.scalar(
        _anime_statement().where(Anime.mal_id == mal_id)
    )
    if anime is None:
        raise ApiError("Anime not found", 404)
    return jsonify({"item": _serialize_anime(anime, detailed=True)})


@app.get(f"{API_PREFIX}/catalogue")
def list_catalogue():
    """Search Anime, Manga, Manhwa, or the combined public catalogue."""
    scope = _content_type_argument(default="ALL")
    return _list_catalogue(CONTENT_TYPE_SCOPES[scope])


@app.get(f"{API_PREFIX}/catalogue/random")
def random_catalogue():
    """Return a scoped random selection from the combined catalogue."""
    scope = _content_type_argument(default="ALL")
    return _random_catalogue(CONTENT_TYPE_SCOPES[scope])


@app.get(f"{API_PREFIX}/catalogue/<content_type>/<int:mal_id>")
def catalogue_detail(content_type: str, mal_id: int):
    """Return a type-qualified detail record without MAL-ID ambiguity."""
    return _catalogue_detail_response(content_type, mal_id)


@app.get(f"{API_PREFIX}/manga")
def list_manga():
    return _list_catalogue(CONTENT_TYPE_SCOPES["MANGA"])


@app.get(f"{API_PREFIX}/manga/random")
def random_manga():
    return _random_catalogue(CONTENT_TYPE_SCOPES["MANGA"])


@app.get(f"{API_PREFIX}/manga/<int:mal_id>")
def manga_detail(mal_id: int):
    return _catalogue_detail_response("MANGA", mal_id)


@app.get(f"{API_PREFIX}/manhwa")
def list_manhwa():
    return _list_catalogue(CONTENT_TYPE_SCOPES["MANHWA"])


@app.get(f"{API_PREFIX}/manhwa/random")
def random_manhwa():
    return _random_catalogue(CONTENT_TYPE_SCOPES["MANHWA"])


@app.get(f"{API_PREFIX}/manhwa/<int:mal_id>")
def manhwa_detail(mal_id: int):
    return _catalogue_detail_response("MANHWA", mal_id)


def _load_genre_names(
    content_types: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        db.session.scalars(
            select(CatalogueFacet.value)
            .where(
                CatalogueFacet.content_type.in_(sorted(content_types)),
                CatalogueFacet.facet_type == "genre",
            )
            .distinct()
            .order_by(CatalogueFacet.value)
        ).all()
    )


def _load_detailed_tag_names(
    content_types: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        db.session.scalars(
            select(CatalogueFacet.value)
            .where(
                CatalogueFacet.content_type.in_(sorted(content_types)),
                CatalogueFacet.facet_type == "tag",
            )
            .distinct()
            .order_by(CatalogueFacet.value)
        ).all()
    )


@app.get(f"{API_PREFIX}/genres")
def list_genres():
    scope = _content_type_argument(default="ANIME")
    content_types = CONTENT_TYPE_SCOPES[scope]
    genres = response_cache.get_or_create(
        ("genres", tuple(sorted(content_types))),
        lambda: _load_genre_names(content_types),
    )
    return jsonify({"items": genres})


@app.get(f"{API_PREFIX}/tags")
def list_detailed_tags():
    """Search one cached detailed-tag catalogue for the selected content."""
    scope = _content_type_argument(default="ANIME")
    content_types = CONTENT_TYPE_SCOPES[scope]
    query = request.args.get("q", "").strip().casefold()
    limit = _integer_argument("limit", minimum=1, maximum=MAX_TAG_OPTIONS) or 50
    all_tags = response_cache.get_or_create(
        ("tags", tuple(sorted(content_types))),
        lambda: _load_detailed_tag_names(content_types),
    )
    if query:
        all_tags = tuple(
            tag for tag in all_tags if query in tag.casefold()
        )
    return jsonify({"items": all_tags[:limit]})


@app.get("/")
@app.get("/<path:path>")
def react_app(path: str = ""):
    """Serve the built React app and let its router handle browser routes."""
    requested_file = FRONTEND_BUILD_DIR / path
    if path and requested_file.is_file():
        return send_from_directory(FRONTEND_BUILD_DIR, path)
    return send_from_directory(FRONTEND_BUILD_DIR, "index.html")


with app.app_context():
    ensure_anime_schema()


if __name__ == "__main__":
    app.run(debug=True, port=8000)

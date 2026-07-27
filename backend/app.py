"""Flask REST API and single-service React application host."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import selectinload

from backend.models import Anime, Genre, db
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
TYPE_ALIASES = {"TV SPECIAL": "SPECIAL"}


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


def _normalized_type(value: str) -> str:
    """Match filter input to the canonical uppercase database type."""
    normalized = " ".join(value.replace("_", " ").split()).upper()
    return TYPE_ALIASES.get(normalized, normalized)


def _serialize_anime(anime: Anime, *, detailed: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": anime.animeID,
        "mal_id": anime.mal_id,
        "title": anime.title,
        "alternative_title": anime.alternative_title,
        "type": anime.type,
        "season": anime.season,
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


def _anime_statement():
    """Base public query that never exposes adult-only Hentai records."""
    legacy_genre = func.unnest(Anime.legacy_genres).column_valued(
        "legacy_genre"
    )
    detailed_genre = func.unnest(Anime.genres_detailed).column_valued(
        "detailed_genre"
    )
    return (
        select(Anime)
        .where(
            ~Anime.genre_entries.any(
                func.lower(func.trim(Genre.name)) == "hentai"
            ),
            ~exists(
                select(1).where(
                    func.lower(func.trim(legacy_genre)) == "hentai"
                )
            ),
            ~exists(
                select(1).where(
                    func.lower(func.trim(detailed_genre)) == "hentai"
                )
            ),
        )
        .options(selectinload(Anime.genre_entries))
    )


def _filtered_anime_statement():
    query = request.args.get("q", "").strip()
    min_score = _float_argument("min_score", minimum=0, maximum=10)
    min_year = _integer_argument("min_year", minimum=1, maximum=3000)
    max_year = _integer_argument("max_year", minimum=1, maximum=3000)
    min_episodes = _integer_argument("min_episodes", minimum=1, maximum=10000)
    anime_types = [_normalized_type(value) for value in _list_argument("type")]
    seasons = [season.lower() for season in _list_argument("season")]
    genres = _list_argument("genre")
    tags = _list_argument("tag")

    invalid_seasons = set(seasons).difference(VALID_SEASONS)
    if invalid_seasons:
        raise ApiError("season must be winter, spring, summer, or fall")

    if min_year is not None and max_year is not None and min_year > max_year:
        raise ApiError("min_year cannot be greater than max_year")

    statement = _anime_statement().where(Anime.score.is_not(None))
    if query:
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_query}%"
        statement = statement.where(
            or_(
                Anime.title.ilike(pattern, escape="\\"),
                Anime.alternative_title.ilike(pattern, escape="\\"),
            )
        )
    if min_score is not None:
        statement = statement.where(Anime.score >= min_score)
    if min_year is not None:
        statement = statement.where(Anime.year >= min_year)
    if max_year is not None:
        statement = statement.where(Anime.year <= max_year)
    if min_episodes is not None:
        statement = statement.where(Anime.episodes >= min_episodes)
    if anime_types:
        statement = statement.where(Anime.type.in_(anime_types))
    if seasons:
        statement = statement.where(Anime.season.in_(seasons))
    for genre in genres:
        statement = statement.where(Anime.genre_entries.any(Genre.name == genre))
    for tag in tags:
        statement = statement.where(Anime.genres_detailed.contains([tag]))
    return statement


@app.get(f"{API_PREFIX}/anime")
def list_anime():
    """Search and filter anime with score-sorted pagination."""
    page = _integer_argument("page", minimum=1) or 1
    per_page = _integer_argument("per_page", minimum=1, maximum=MAX_PAGE_SIZE) or 24
    statement = _filtered_anime_statement()
    total = db.session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    items = db.session.scalars(
        statement.order_by(Anime.score.desc(), Anime.title).offset((page - 1) * per_page).limit(per_page)
    ).all()
    return jsonify(
        {
            "items": [_serialize_anime(anime) for anime in items],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total or 0,
                "pages": ((total or 0) + per_page - 1) // per_page,
            },
        }
    )


@app.get(f"{API_PREFIX}/anime/random")
def random_anime():
    """Return a small random selection of rated anime."""
    limit = _integer_argument("limit", minimum=1, maximum=12) or 6
    anime = db.session.scalars(
        _anime_statement()
        .where(Anime.score.is_not(None))
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
    total = db.session.scalar(select(func.count()).select_from(public_season))
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
                "total": total or 0,
                "pages": ((total or 0) + limit - 1) // limit,
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


@app.get(f"{API_PREFIX}/genres")
def list_genres():
    genres = db.session.scalars(
        select(Genre.name)
        .where(func.lower(func.trim(Genre.name)) != "hentai")
        .order_by(Genre.name)
    ).all()
    return jsonify({"items": genres})


@app.get(f"{API_PREFIX}/tags")
def list_detailed_tags():
    """Search detailed genre tags without sending thousands of options to the UI."""
    query = request.args.get("q", "").strip()
    limit = _integer_argument("limit", minimum=1, maximum=MAX_TAG_OPTIONS) or 50
    detailed_tags = select(func.unnest(Anime.genres_detailed).label("tag")).subquery()
    statement = select(detailed_tags.c.tag).where(detailed_tags.c.tag.is_not(None))
    statement = statement.where(
        func.lower(func.trim(detailed_tags.c.tag)) != "hentai"
    )
    if query:
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        statement = statement.where(detailed_tags.c.tag.ilike(f"%{escaped_query}%", escape="\\"))
    tags = db.session.scalars(
        statement
        .distinct()
        .order_by(detailed_tags.c.tag)
        .limit(limit)
    ).all()
    return jsonify({"items": tags})


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

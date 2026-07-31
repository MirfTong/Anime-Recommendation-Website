"""Small, additive database migrations required by the catalogue application."""

import re
from threading import Lock

from sqlalchemy import text

from backend.models import db


CATALOGUE_SCHEMA_VERSION = 3
CATALOGUE_SCHEMA_LOCK_ID = 5_423_769_101
CATALOGUE_SCHEMA_VERSION_TABLE = "catalogue_schema_version"

_catalogue_schema_ready = False
_catalogue_schema_process_lock = Lock()


def _column_exists(table_name: str, column_name: str) -> bool:
    return bool(
        db.session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() "
                "AND table_name = :table_name "
                "AND column_name = :column_name"
                ")"
            ),
            {"table_name": table_name, "column_name": column_name},
        )
    )


def _schema_version_is_current() -> bool:
    version_table = db.session.scalar(
        text("SELECT to_regclass(:table_name)"),
        {"table_name": CATALOGUE_SCHEMA_VERSION_TABLE},
    )
    if version_table is None:
        return False
    return bool(
        db.session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM catalogue_schema_version "
                "WHERE version = :version"
                ")"
            ),
            {"version": CATALOGUE_SCHEMA_VERSION},
        )
    )


def refresh_catalogue_facets(*, commit: bool = True) -> int:
    """Rebuild indexed public genre/tag options from normalized catalogue data."""
    db.session.execute(text("DELETE FROM catalogue_facet"))
    db.session.execute(
        text(
            "INSERT INTO catalogue_facet (content_type, facet_type, value) "
            "SELECT DISTINCT source.content_type, source.facet_type, "
            "LEFT(TRIM(source.value), 255) "
            "FROM ("
            "SELECT 'ANIME' AS content_type, 'genre' AS facet_type, "
            "genre.name AS value "
            "FROM anime "
            "JOIN anime_genre ON anime_genre.anime_id = anime.anime_id "
            "JOIN genre ON genre.id = anime_genre.genre_id "
            "WHERE anime.is_adult = FALSE "
            "UNION ALL "
            "SELECT manga.content_type, 'genre', genre.name "
            "FROM manga "
            "JOIN manga_genre ON manga_genre.manga_id = manga.manga_id "
            "JOIN genre ON genre.id = manga_genre.genre_id "
            "WHERE manga.is_adult = FALSE "
            "UNION ALL "
            "SELECT 'ANIME', 'tag', detail.value "
            "FROM anime "
            "CROSS JOIN LATERAL unnest(anime.genres_detailed) AS detail(value) "
            "WHERE anime.is_adult = FALSE "
            "UNION ALL "
            "SELECT manga.content_type, 'tag', detail.value "
            "FROM manga "
            "CROSS JOIN LATERAL unnest(manga.genres_detailed) AS detail(value) "
            "WHERE manga.is_adult = FALSE "
            "UNION ALL "
            "SELECT 'ANIME', 'studio', studio.name "
            "FROM anime "
            "JOIN anime_studio ON anime_studio.anime_id = anime.anime_id "
            "JOIN studio ON studio.id = anime_studio.studio_id "
            "WHERE anime.is_adult = FALSE "
            "UNION ALL "
            "SELECT 'ANIME', 'streaming_service', streaming_service.name "
            "FROM anime "
            "JOIN anime_streaming_service "
            "ON anime_streaming_service.anime_id = anime.anime_id "
            "JOIN streaming_service "
            "ON streaming_service.id = "
            "anime_streaming_service.streaming_service_id "
            "WHERE anime.is_adult = FALSE "
            "UNION ALL "
            "SELECT manga.content_type, 'author', author.name "
            "FROM manga "
            "JOIN manga_author ON manga_author.manga_id = manga.manga_id "
            "JOIN author ON author.id = manga_author.author_id "
            "WHERE manga.is_adult = FALSE"
            ") AS source "
            "WHERE source.value IS NOT NULL "
            "AND TRIM(source.value) <> '' "
            "AND LOWER(TRIM(source.value)) NOT IN ('hentai', 'erotica') "
            "ON CONFLICT DO NOTHING"
        )
    )
    total = int(
        db.session.scalar(text("SELECT COUNT(*) FROM catalogue_facet")) or 0
    )
    if commit:
        db.session.commit()
    return total


def _apply_catalogue_schema_migration(connection) -> None:
    """Apply the current migration while the transaction advisory lock is held."""
    # pg_trgm makes the API's leading-wildcard title searches indexable. It is
    # a trusted PostgreSQL extension and must exist before ORM indexes are made.
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    missing_adult_flags = {
        table_name
        for table_name in ("anime", "manga")
        if not _column_exists(table_name, "is_adult")
    }
    # Use the session's locked transaction rather than opening another engine
    # connection that would sit outside the advisory-lock boundary.
    db.metadata.create_all(bind=connection)

    # The original facet table allowed only genres and tags. Widen its value
    # column and check constraint once so studio/service options can use the
    # same precomputed, indexed lookup path.
    db.session.execute(
        text(
            "ALTER TABLE catalogue_facet ALTER COLUMN facet_type "
            "TYPE VARCHAR(30)"
        )
    )
    facet_constraint = db.session.scalar(
        text(
            "SELECT pg_get_constraintdef(oid) "
            "FROM pg_constraint "
            "WHERE conrelid = 'catalogue_facet'::regclass "
            "AND conname = 'ck_catalogue_facet_type'"
        )
    )
    required_facet_types = {
        "genre",
        "tag",
        "studio",
        "streaming_service",
        "author",
    }
    constraint_facet_types = (
        set(re.findall(r"'([^']+)'", facet_constraint))
        if isinstance(facet_constraint, str)
        else set()
    )
    if constraint_facet_types != required_facet_types:
        db.session.execute(
            text(
                "ALTER TABLE catalogue_facet DROP CONSTRAINT IF EXISTS "
                "ck_catalogue_facet_type"
            )
        )
        db.session.execute(
            text(
                "ALTER TABLE catalogue_facet ADD CONSTRAINT "
                "ck_catalogue_facet_type CHECK (facet_type IN "
                "('genre', 'tag', 'studio', 'streaming_service', 'author'))"
            )
        )

    # Older CSV imports required these fields, but Jikan can legitimately omit
    # them for unreleased or currently airing titles.
    for column in ("year", "score", "episodes"):
        db.session.execute(
            text(f"ALTER TABLE anime ALTER COLUMN {column} DROP NOT NULL")
        )

    for definition in (
        "last_jikan_sync TIMESTAMP WITH TIME ZONE",
        "last_jikan_attempt TIMESTAMP WITH TIME ZONE",
        "last_streaming_attempt TIMESTAMP WITH TIME ZONE",
        "last_season_attempt TIMESTAMP WITH TIME ZONE",
        "mal_id INTEGER",
        "season VARCHAR(6)",
        "status VARCHAR(30)",
        "synopsis TEXT",
        "is_adult BOOLEAN NOT NULL DEFAULT FALSE",
    ):
        db.session.execute(
            text(f"ALTER TABLE anime ADD COLUMN IF NOT EXISTS {definition}")
        )

    # Keep legacy CSV labels and Jikan labels aligned with the exact values
    # used by the frontend type filter.
    db.session.execute(
        text(
            "UPDATE anime SET type = CASE "
            "WHEN REPLACE(UPPER(TRIM(type)), '_', ' ') = 'TV SPECIAL' "
            "THEN 'SPECIAL' "
            "ELSE UPPER(TRIM(type)) END "
            "WHERE type IS NOT NULL AND type <> CASE "
            "WHEN REPLACE(UPPER(TRIM(type)), '_', ' ') = 'TV SPECIAL' "
            "THEN 'SPECIAL' "
            "ELSE UPPER(TRIM(type)) END"
        )
    )

    db.session.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_anime_mal_id "
            "ON anime (mal_id)"
        )
    )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_last_jikan_attempt "
            "ON anime (last_jikan_attempt)"
        )
    )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_last_streaming_attempt "
            "ON anime (last_streaming_attempt)"
        )
    )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_last_season_attempt "
            "ON anime (last_season_attempt)"
        )
    )
    db.session.execute(
        text("CREATE INDEX IF NOT EXISTS ix_anime_season ON anime (season)")
    )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_season_score "
            "ON anime (season, score)"
        )
    )
    db.session.execute(
        text(
            "UPDATE anime SET status = CASE "
            "WHEN REPLACE(UPPER(TRIM(status)), ' ', '_') "
            "IN ('CURRENTLY_AIRING', 'AIRING') "
            "THEN 'CURRENTLY_AIRING' "
            "WHEN REPLACE(UPPER(TRIM(status)), ' ', '_') "
            "IN ('FINISHED_AIRING', 'FINISHED') "
            "THEN 'FINISHED_AIRING' "
            "WHEN REPLACE(UPPER(TRIM(status)), ' ', '_') "
            "IN ('NOT_YET_AIRED', 'NOT_YET_AIRING') "
            "THEN 'NOT_YET_AIRED' "
            "ELSE status END "
            "WHERE status IS NOT NULL"
        )
    )
    db.session.execute(
        text(
            "ALTER TABLE manga ADD COLUMN IF NOT EXISTS "
            "is_adult BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )

    if "anime" in missing_adult_flags:
        db.session.execute(
            text(
                "UPDATE anime SET is_adult = TRUE "
                "WHERE is_adult = FALSE AND ("
                "EXISTS ("
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
                "))"
            )
        )
    if "manga" in missing_adult_flags:
        db.session.execute(
            text(
                "UPDATE manga SET is_adult = TRUE "
                "WHERE is_adult = FALSE AND ("
                "EXISTS ("
                "SELECT 1 FROM manga_genre "
                "JOIN genre ON genre.id = manga_genre.genre_id "
                "WHERE manga_genre.manga_id = manga.manga_id "
                "AND LOWER(TRIM(genre.name)) IN ('hentai', 'erotica')"
                ") OR EXISTS ("
                "SELECT 1 FROM unnest(manga.genres) AS legacy(value) "
                "WHERE LOWER(TRIM(legacy.value)) IN ('hentai', 'erotica')"
                ") OR EXISTS ("
                "SELECT 1 FROM unnest(manga.genres_detailed) AS detail(value) "
                "WHERE LOWER(TRIM(detail.value)) IN ('hentai', 'erotica')"
                "))"
            )
        )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_genre_genre_anime "
            "ON anime_genre (genre_id, anime_id)"
        )
    )
    db.session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_anime_genres_detailed_gin "
            "ON anime USING GIN (genres_detailed)"
        )
    )
    for index_sql in (
        "CREATE INDEX IF NOT EXISTS ix_anime_title_trgm "
        "ON anime USING GIN (title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_anime_alternative_title_trgm "
        "ON anime USING GIN (alternative_title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_anime_is_adult "
        "ON anime (is_adult)",
        "CREATE INDEX IF NOT EXISTS ix_anime_public_score "
        "ON anime (is_adult, score)",
        "CREATE INDEX IF NOT EXISTS ix_anime_status_score "
        "ON anime (status, score DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_studio_normalized_name "
        "ON studio (normalized_name)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_studio_mal_id "
        "ON studio (mal_id)",
        "CREATE INDEX IF NOT EXISTS ix_anime_studio_studio_anime "
        "ON anime_studio (studio_id, anime_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_streaming_service_normalized_name "
        "ON streaming_service (normalized_name)",
        "CREATE INDEX IF NOT EXISTS "
        "ix_anime_streaming_service_service_anime "
        "ON anime_streaming_service (streaming_service_id, anime_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_author_normalized_name "
        "ON author (normalized_name)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_author_mal_id "
        "ON author (mal_id)",
        "CREATE INDEX IF NOT EXISTS ix_manga_author_author_manga "
        "ON manga_author (author_id, manga_id)",
        "CREATE INDEX IF NOT EXISTS ix_manga_title_trgm "
        "ON manga USING GIN (title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_manga_alternative_title_trgm "
        "ON manga USING GIN (alternative_title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_manga_is_adult "
        "ON manga (is_adult)",
        "CREATE INDEX IF NOT EXISTS ix_manga_content_public_score "
        "ON manga (content_type, is_adult, score)",
        "CREATE INDEX IF NOT EXISTS ix_manga_content_status_normalized_score "
        "ON manga (content_type, LOWER(BTRIM(status)), score DESC)",
    ):
        db.session.execute(text(index_sql))
    has_facets = db.session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM catalogue_facet LIMIT 1)")
    )
    if not has_facets:
        refresh_catalogue_facets(commit=False)


def ensure_catalogue_schema() -> None:
    """Apply each catalogue schema version once with cross-process locking."""
    global _catalogue_schema_ready

    if _catalogue_schema_ready:
        return

    with _catalogue_schema_process_lock:
        if _catalogue_schema_ready:
            return
        try:
            # The common path is read-only and avoids PostgreSQL DDL and
            # advisory locks after this schema version has been recorded.
            if _schema_version_is_current():
                db.session.commit()
                _catalogue_schema_ready = True
                return

            db.session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": CATALOGUE_SCHEMA_LOCK_ID},
            )
            # Another Render worker or GitHub Action may have completed the
            # migration while this process waited for the transaction lock.
            if _schema_version_is_current():
                db.session.commit()
                _catalogue_schema_ready = True
                return

            db.session.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS catalogue_schema_version ("
                    "version INTEGER PRIMARY KEY, "
                    "applied_at TIMESTAMP WITH TIME ZONE NOT NULL "
                    "DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
            connection = db.session.connection()
            _apply_catalogue_schema_migration(connection)
            db.session.execute(
                text(
                    "INSERT INTO catalogue_schema_version (version) "
                    "VALUES (:version) ON CONFLICT (version) DO NOTHING"
                ),
                {"version": CATALOGUE_SCHEMA_VERSION},
            )
            db.session.commit()
            _catalogue_schema_ready = True
        except BaseException:
            db.session.rollback()
            raise


def ensure_anime_schema() -> None:
    """Backward-compatible entry point used by the existing anime jobs."""
    ensure_catalogue_schema()

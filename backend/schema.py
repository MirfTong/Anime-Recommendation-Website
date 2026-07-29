"""Small, additive database migrations required by the catalogue application."""

from sqlalchemy import text

from backend.models import db


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


def refresh_catalogue_facets() -> int:
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
    db.session.commit()
    return total


def ensure_catalogue_schema() -> None:
    """Create anime/manga tables and apply safe additive catalogue migrations."""
    # pg_trgm makes the API's leading-wildcard title searches indexable. It is
    # a trusted PostgreSQL extension and must exist before ORM indexes are made.
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    db.session.commit()
    missing_adult_flags = {
        table_name
        for table_name in ("anime", "manga")
        if not _column_exists(table_name, "is_adult")
    }
    db.create_all()

    # Older CSV imports required these fields, but Jikan can legitimately omit
    # them for unreleased or currently airing titles.
    for column in ("year", "score", "episodes"):
        db.session.execute(
            text(f"ALTER TABLE anime ALTER COLUMN {column} DROP NOT NULL")
        )

    for definition in (
        "last_jikan_sync TIMESTAMP WITH TIME ZONE",
        "last_jikan_attempt TIMESTAMP WITH TIME ZONE",
        "last_season_attempt TIMESTAMP WITH TIME ZONE",
        "mal_id INTEGER",
        "season VARCHAR(6)",
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
    db.session.commit()
    has_facets = db.session.scalar(
        text("SELECT EXISTS (SELECT 1 FROM catalogue_facet LIMIT 1)")
    )
    if not has_facets:
        refresh_catalogue_facets()


def ensure_anime_schema() -> None:
    """Backward-compatible entry point used by the existing anime jobs."""
    ensure_catalogue_schema()

"""Small, additive database migrations required by the catalogue application."""

from sqlalchemy import text

from backend.models import db


def ensure_catalogue_schema() -> None:
    """Create anime/manga tables and apply safe additive catalogue migrations."""
    # pg_trgm makes the API's leading-wildcard title searches indexable. It is
    # a trusted PostgreSQL extension and must exist before ORM indexes are made.
    db.session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    db.session.commit()
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
        "CREATE INDEX IF NOT EXISTS ix_manga_title_trgm "
        "ON manga USING GIN (title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_manga_alternative_title_trgm "
        "ON manga USING GIN (alternative_title gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_manga_content_status_normalized_score "
        "ON manga (content_type, LOWER(BTRIM(status)), score DESC)",
    ):
        db.session.execute(text(index_sql))
    db.session.commit()


def ensure_anime_schema() -> None:
    """Backward-compatible entry point used by the existing anime jobs."""
    ensure_catalogue_schema()

"""Small, additive database migrations required by the catalogue application."""

from sqlalchemy import text

from backend.models import db


def ensure_anime_schema() -> None:
    """Create the catalogue schema and safely add columns used by newer releases."""
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
    db.session.commit()

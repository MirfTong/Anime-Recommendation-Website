"""Report database storage and safely preview targeted catalogue cleanup."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection


@dataclass(frozen=True)
class CleanupTarget:
    label: str
    count_sql: str
    delete_sql: str


def cleanup_targets(retention_days: int) -> tuple[CleanupTarget, ...]:
    retention_filter = (
        "visit_date < CURRENT_DATE - "
        f"INTERVAL '{retention_days} days'"
    )
    return (
        CleanupTarget(
            f"site_visit rows older than {retention_days} days",
            f"SELECT COUNT(*) FROM site_visit WHERE {retention_filter}",
            f"DELETE FROM site_visit WHERE {retention_filter}",
        ),
        CleanupTarget(
            "unreferenced authors",
            "SELECT COUNT(*) FROM author WHERE NOT EXISTS ("
            "SELECT 1 FROM manga_author WHERE manga_author.author_id = author.id)",
            "DELETE FROM author WHERE NOT EXISTS ("
            "SELECT 1 FROM manga_author WHERE manga_author.author_id = author.id)",
        ),
        CleanupTarget(
            "unreferenced studios",
            "SELECT COUNT(*) FROM studio WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_studio WHERE anime_studio.studio_id = studio.id)",
            "DELETE FROM studio WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_studio WHERE anime_studio.studio_id = studio.id)",
        ),
        CleanupTarget(
            "unreferenced streaming services",
            "SELECT COUNT(*) FROM streaming_service WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_streaming_service WHERE "
            "anime_streaming_service.streaming_service_id = streaming_service.id)",
            "DELETE FROM streaming_service WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_streaming_service WHERE "
            "anime_streaming_service.streaming_service_id = streaming_service.id)",
        ),
        CleanupTarget(
            "unreferenced genres",
            "SELECT COUNT(*) FROM genre WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_genre WHERE anime_genre.genre_id = genre.id) "
            "AND NOT EXISTS (SELECT 1 FROM manga_genre WHERE "
            "manga_genre.genre_id = genre.id)",
            "DELETE FROM genre WHERE NOT EXISTS ("
            "SELECT 1 FROM anime_genre WHERE anime_genre.genre_id = genre.id) "
            "AND NOT EXISTS (SELECT 1 FROM manga_genre WHERE "
            "manga_genre.genre_id = genre.id)",
        ),
    )


DUPLICATE_CHECKS = (
    (
        "anime.mal_id",
        "SELECT COUNT(*) - COUNT(DISTINCT mal_id) FROM anime "
        "WHERE mal_id IS NOT NULL",
    ),
    (
        "manga.mal_id",
        "SELECT COUNT(*) - COUNT(DISTINCT mal_id) FROM manga",
    ),
    (
        "site_visit natural key",
        "SELECT COUNT(*) - COUNT(DISTINCT "
        "(visitor_token_hash, visit_date, route)) FROM site_visit",
    ),
    (
        "anime_genre pair",
        "SELECT COUNT(*) - COUNT(DISTINCT (anime_id, genre_id)) "
        "FROM anime_genre",
    ),
    (
        "manga_genre pair",
        "SELECT COUNT(*) - COUNT(DISTINCT (manga_id, genre_id)) "
        "FROM manga_genre",
    ),
    (
        "anime_studio pair",
        "SELECT COUNT(*) - COUNT(DISTINCT (anime_id, studio_id)) "
        "FROM anime_studio",
    ),
    (
        "anime_streaming_service pair",
        "SELECT COUNT(*) - COUNT(DISTINCT "
        "(anime_id, streaming_service_id)) FROM anime_streaming_service",
    ),
    (
        "manga_author pair",
        "SELECT COUNT(*) - COUNT(DISTINCT (manga_id, author_id)) "
        "FROM manga_author",
    ),
)


def report_storage(connection: Connection) -> None:
    database_size = connection.execute(
        text(
            "SELECT pg_size_pretty(pg_database_size(current_database())), "
            "pg_database_size(current_database())"
        )
    ).one()
    print(f"Logical database size: {database_size[0]} ({database_size[1]} bytes)")
    rows = connection.execute(
        text(
            "SELECT relname, pg_total_relation_size(relid) AS total_bytes, "
            "pg_size_pretty(pg_total_relation_size(relid)) AS total_size, "
            "pg_size_pretty(pg_relation_size(relid)) AS table_size, "
            "pg_size_pretty(pg_indexes_size(relid)) AS index_size, "
            "n_live_tup, n_dead_tup "
            "FROM pg_stat_user_tables "
            "ORDER BY pg_total_relation_size(relid) DESC"
        )
    ).mappings()
    print("\nRelations (largest first):")
    for row in rows:
        print(
            f"- {row['relname']}: total={row['total_size']}, "
            f"table={row['table_size']}, indexes={row['index_size']}, "
            f"estimated_live={row['n_live_tup']}, dead={row['n_dead_tup']}"
        )


def report_duplicates(connection: Connection) -> None:
    print("\nDuplicate-key audit:")
    for label, statement in DUPLICATE_CHECKS:
        count = int(connection.scalar(text(statement)) or 0)
        print(f"- {label}: {count}")


def run_cleanup(
    connection: Connection, *, retention_days: int, apply: bool
) -> int:
    action = "Applying" if apply else "Dry run"
    print(f"\n{action} targeted cleanup:")
    total = 0
    for target in cleanup_targets(retention_days):
        count = int(connection.scalar(text(target.count_sql)) or 0)
        total += count
        print(f"- {target.label}: {count}")
        if apply and count:
            connection.execute(text(target.delete_sql))
    if not apply:
        print(
            "No rows were deleted. Re-run with --apply --confirm CLEANUP "
            "only after reviewing these counts and taking a backup."
        )
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retention-days",
        type=int,
        default=365,
        help="Site-visit retention window used by the cleanup preview.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete only the rows listed by the cleanup preview.",
    )
    parser.add_argument(
        "--confirm",
        help="Required value CLEANUP when --apply is used.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.retention_days <= 0:
        raise SystemExit("--retention-days must be positive")
    if args.apply and args.confirm != "CLEANUP":
        raise SystemExit("--apply requires --confirm CLEANUP")

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured")

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.begin() as connection:
            if not args.apply:
                connection.execute(text("SET TRANSACTION READ ONLY"))
            report_storage(connection)
            report_duplicates(connection)
            run_cleanup(
                connection,
                retention_days=args.retention_days,
                apply=args.apply,
            )
    except Exception as error:
        raise SystemExit(
            "Database maintenance failed without changing credentials or "
            f"configuration ({type(error).__name__})."
        ) from None


if __name__ == "__main__":
    main()

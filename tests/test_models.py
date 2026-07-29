import unittest
from pathlib import Path

from sqlalchemy import CheckConstraint

from backend.models import Genre, Manga, MangaGenre


SCHEMA_SOURCE = (
    Path(__file__).resolve().parents[1] / "backend" / "schema.py"
)


class MangaSchemaTests(unittest.TestCase):
    def test_manga_table_contains_the_complete_catalogue_shape(self):
        columns = set(Manga.__table__.columns.keys())

        self.assertTrue(
            {
                "manga_id",
                "mal_id",
                "content_type",
                "title",
                "alternative_title",
                "synopsis",
                "manga_type",
                "publication_year",
                "status",
                "score",
                "chapters",
                "volumes",
                "mal_url",
                "image_url",
                "genres",
                "genres_detailed",
                "last_jikan_sync",
                "last_jikan_attempt",
            }.issubset(columns)
        )
        self.assertTrue(Manga.__table__.c.mal_id.unique)

    def test_content_type_constraint_allows_only_manga_and_manhwa(self):
        checks = [
            str(constraint.sqltext)
            for constraint in Manga.__table__.constraints
            if isinstance(constraint, CheckConstraint)
        ]

        self.assertTrue(
            any(
                "MANGA" in expression and "MANHWA" in expression
                for expression in checks
            )
        )

    def test_manga_genres_reuse_the_shared_genre_table(self):
        foreign_key_targets = {
            foreign_key.target_fullname
            for foreign_key in MangaGenre.__table__.foreign_keys
        }

        self.assertEqual(
            foreign_key_targets,
            {"manga.manga_id", "genre.id"},
        )
        self.assertIs(
            MangaGenre.__mapper__.relationships["genre"].entity.class_,
            Genre,
        )

    def test_frequent_filter_and_search_indexes_are_declared(self):
        index_names = {index.name for index in Manga.__table__.indexes}

        self.assertTrue(
            {
                "ix_manga_content_score",
                "ix_manga_content_year",
                "ix_manga_content_chapters",
                "ix_manga_content_volumes",
                "ix_manga_content_status_score",
                "ix_manga_genres_detailed_gin",
                "ix_manga_title_trgm",
                "ix_manga_alternative_title_trgm",
            }.issubset(index_names)
        )
        schema_source = SCHEMA_SOURCE.read_text(encoding="utf-8")
        self.assertIn("ix_manga_content_status_normalized_score", schema_source)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", schema_source)


if __name__ == "__main__":
    unittest.main()

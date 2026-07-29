import unittest
from pathlib import Path

from sqlalchemy import CheckConstraint

from backend.models import Anime, CatalogueFacet, Genre, Manga, MangaGenre


SCHEMA_SOURCE = (
    Path(__file__).resolve().parents[1] / "backend" / "schema.py"
)


class MangaSchemaTests(unittest.TestCase):
    def test_anime_table_contains_nullable_indexed_airing_status(self):
        self.assertIn("status", Anime.__table__.columns)
        self.assertTrue(Anime.__table__.c.status.nullable)
        self.assertIn(
            "ix_anime_status_score",
            {index.name for index in Anime.__table__.indexes},
        )
        schema_source = SCHEMA_SOURCE.read_text(encoding="utf-8")
        self.assertIn('"status VARCHAR(30)"', schema_source)
        self.assertIn(
            "CREATE INDEX IF NOT EXISTS ix_anime_status_score",
            schema_source,
        )

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
                "is_adult",
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
                "ix_manga_content_public_score",
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
        self.assertIn("CREATE INDEX IF NOT EXISTS ix_anime_is_adult", schema_source)
        self.assertIn("CREATE INDEX IF NOT EXISTS ix_manga_is_adult", schema_source)
        self.assertIn("ix_manga_content_status_normalized_score", schema_source)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", schema_source)

    def test_public_catalogue_flags_are_indexed_for_both_media_tables(self):
        self.assertFalse(Anime.__table__.c.is_adult.nullable)
        self.assertFalse(Manga.__table__.c.is_adult.nullable)
        self.assertIn(
            "ix_anime_public_score",
            {index.name for index in Anime.__table__.indexes},
        )
        self.assertIn(
            "ix_manga_content_public_score",
            {index.name for index in Manga.__table__.indexes},
        )

    def test_catalogue_facets_have_a_composite_lookup_key(self):
        self.assertEqual(
            {
                column.name
                for column in CatalogueFacet.__table__.primary_key.columns
            },
            {"content_type", "facet_type", "value"},
        )
        schema_source = SCHEMA_SOURCE.read_text(encoding="utf-8")
        self.assertIn("refresh_catalogue_facets", schema_source)
        self.assertIn("INSERT INTO catalogue_facet", schema_source)


if __name__ == "__main__":
    unittest.main()

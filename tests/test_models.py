import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import CheckConstraint

from backend import schema as catalogue_schema
from backend.models import (
    Anime,
    AnimeStreamingService,
    AnimeStudio,
    CatalogueFacet,
    Genre,
    Manga,
    MangaGenre,
    StreamingService,
    Studio,
)


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

    def test_anime_studios_use_a_normalized_many_to_many_schema(self):
        self.assertTrue(Studio.__table__.c.mal_id.unique)
        self.assertTrue(Studio.__table__.c.normalized_name.unique)
        self.assertEqual(
            {
                column.name
                for column in AnimeStudio.__table__.primary_key.columns
            },
            {"anime_id", "studio_id"},
        )
        self.assertEqual(
            {
                foreign_key.target_fullname
                for foreign_key in AnimeStudio.__table__.foreign_keys
            },
            {"anime.anime_id", "studio.id"},
        )
        self.assertIn(
            "ix_anime_studio_studio_anime",
            {index.name for index in AnimeStudio.__table__.indexes},
        )
        self.assertIs(
            AnimeStudio.__mapper__.relationships["studio"].entity.class_,
            Studio,
        )

    def test_streaming_urls_live_on_the_normalized_anime_service_link(self):
        self.assertTrue(StreamingService.__table__.c.normalized_name.unique)
        self.assertIn("url", AnimeStreamingService.__table__.columns)
        self.assertEqual(
            {
                column.name
                for column in AnimeStreamingService.__table__.primary_key.columns
            },
            {"anime_id", "streaming_service_id"},
        )
        self.assertEqual(
            {
                foreign_key.target_fullname
                for foreign_key in AnimeStreamingService.__table__.foreign_keys
            },
            {"anime.anime_id", "streaming_service.id"},
        )
        self.assertIn(
            "ix_anime_streaming_service_service_anime",
            {
                index.name
                for index in AnimeStreamingService.__table__.indexes
            },
        )
        self.assertIs(
            AnimeStreamingService.__mapper__.relationships[
                "streaming_service"
            ].entity.class_,
            StreamingService,
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

    def test_catalogue_facets_support_studio_and_streaming_options(self):
        facet_checks = [
            str(constraint.sqltext)
            for constraint in CatalogueFacet.__table__.constraints
            if isinstance(constraint, CheckConstraint)
            and constraint.name == "ck_catalogue_facet_type"
        ]

        self.assertEqual(CatalogueFacet.__table__.c.facet_type.type.length, 30)
        self.assertTrue(
            any(
                "studio" in expression
                and "streaming_service" in expression
                for expression in facet_checks
            )
        )
        schema_source = SCHEMA_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "ALTER TABLE catalogue_facet ALTER COLUMN facet_type",
            schema_source,
        )
        self.assertIn(
            "'genre', 'tag', 'studio', 'streaming_service'",
            schema_source,
        )
        self.assertIn("JOIN anime_studio", schema_source)
        self.assertIn("JOIN anime_streaming_service", schema_source)

    def test_schema_bootstrap_is_versioned_and_cross_process_safe(self):
        schema_source = SCHEMA_SOURCE.read_text(encoding="utf-8")

        self.assertIn("CATALOGUE_SCHEMA_VERSION", schema_source)
        self.assertIn("catalogue_schema_version", schema_source)
        self.assertIn("pg_advisory_xact_lock", schema_source)
        self.assertIn("_schema_version_is_current", schema_source)
        self.assertIn("db.metadata.create_all(bind=connection)", schema_source)
        self.assertNotIn("db.create_all()", schema_source)
        self.assertIn(
            'required_facet_types = {"genre", "tag", "studio", "streaming_service"}',
            schema_source,
        )
        self.assertIn(
            "constraint_facet_types != required_facet_types",
            schema_source,
        )

    def test_schema_bootstrap_double_checks_under_lock_and_runs_once(self):
        mock_db = MagicMock()
        connection = object()
        mock_db.session.connection.return_value = connection

        with (
            patch.object(catalogue_schema, "db", mock_db),
            patch.object(
                catalogue_schema,
                "_catalogue_schema_ready",
                False,
            ),
            patch.object(
                catalogue_schema,
                "_schema_version_is_current",
                side_effect=(False, False),
            ) as version_check,
            patch.object(
                catalogue_schema,
                "_apply_catalogue_schema_migration",
            ) as apply_migration,
        ):
            catalogue_schema.ensure_catalogue_schema()
            catalogue_schema.ensure_catalogue_schema()

        self.assertEqual(version_check.call_count, 2)
        apply_migration.assert_called_once_with(connection)
        self.assertEqual(mock_db.session.commit.call_count, 1)
        statements = [
            str(call.args[0])
            for call in mock_db.session.execute.call_args_list
        ]
        self.assertTrue(
            any("pg_advisory_xact_lock" in statement for statement in statements)
        )

    def test_current_schema_version_skips_lock_and_ddl(self):
        mock_db = MagicMock()

        with (
            patch.object(catalogue_schema, "db", mock_db),
            patch.object(
                catalogue_schema,
                "_catalogue_schema_ready",
                False,
            ),
            patch.object(
                catalogue_schema,
                "_schema_version_is_current",
                return_value=True,
            ),
            patch.object(
                catalogue_schema,
                "_apply_catalogue_schema_migration",
            ) as apply_migration,
        ):
            catalogue_schema.ensure_catalogue_schema()

        apply_migration.assert_not_called()
        mock_db.session.execute.assert_not_called()
        mock_db.session.commit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

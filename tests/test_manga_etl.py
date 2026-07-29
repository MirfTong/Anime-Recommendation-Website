import os
import unittest
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

# Importing the Flask module normally applies the PostgreSQL schema eagerly.
# These tests mock every persistence boundary, so suppress that import-time
# migration and use an isolated in-memory URI rather than touching a real DB.
os.environ.setdefault("DATABASE_URL", "sqlite://")
from backend import schema as schema_module

with patch.object(schema_module, "ensure_anime_schema"):
    import backend.app as app_module

app_module.ensure_anime_schema = schema_module.ensure_anime_schema

from backend.jobs.manga_etl import (
    MANGA_PROVIDER_TYPES,
    MANGA_STATE_KEYS,
    MangaPageApplyResult,
    MangaTypeSyncResult,
    _apply_manga_page,
    _publication_year,
    _sync_manga_type,
    _update_manga,
    is_adult_content,
    refresh_manga_catalogue,
    sync_manga_catalogue,
)
from backend.models import Genre, Manga
from backend.services.jikan_client import JikanMangaPage, JikanTemporaryError


def manga_record(
    *,
    mal_id=1,
    content_type="MANGA",
    title="Existing title",
):
    return Manga(
        mangaID=mal_id,
        mal_id=mal_id,
        content_type=content_type,
        title=title,
        alternative_title=None,
        synopsis=None,
        manga_type=content_type.title(),
        publication_year=2020,
        status="Publishing",
        score=7.0,
        chapters=1,
        volumes=1,
        mal_url=f"https://myanimelist.net/manga/{mal_id}",
        image_url="",
        legacy_genres=[],
        genres_detailed=[],
    )


def http_error(url: str, status: int) -> HTTPError:
    return HTTPError(url, status, "request failed", Message(), None)


class MangaMappingTests(unittest.TestCase):
    def test_maps_every_catalogue_field_and_normalized_genres(self):
        manga = manga_record()
        drama = Genre(name="Drama")
        school = Genre(name="School")
        data = {
            "mal_id": 1,
            "type": "Manga",
            "title": "Mapped title",
            "title_english": "English title",
            "title_japanese": "Japanese title",
            "synopsis": "  A mapped synopsis.  ",
            "published": {
                "from": "2005-01-01T00:00:00+00:00",
                "prop": {"from": {"year": 2006}},
            },
            "status": "Finished",
            "score": 8.75,
            "chapters": 42,
            "volumes": 7,
            "url": "https://myanimelist.net/manga/1/Mapped",
            "images": {
                "jpg": {
                    "image_url": "https://example.test/small.jpg",
                    "large_image_url": "https://example.test/large.jpg",
                }
            },
            "genres": [{"name": "Drama"}],
            "explicit_genres": [],
            "themes": [{"name": "School"}],
            "demographics": [{"name": "Seinen"}],
        }

        _update_manga(
            manga,
            data,
            {"Drama": drama, "School": school},
            expected_content_type="MANGA",
        )

        self.assertEqual(manga.content_type, "MANGA")
        self.assertEqual(manga.title, "Mapped title")
        self.assertEqual(manga.alternative_title, "English title")
        self.assertEqual(manga.synopsis, "A mapped synopsis.")
        self.assertEqual(manga.manga_type, "Manga")
        self.assertEqual(manga.publication_year, 2006)
        self.assertEqual(manga.status, "Finished")
        self.assertEqual(manga.score, 8.75)
        self.assertEqual(manga.chapters, 42)
        self.assertEqual(manga.volumes, 7)
        self.assertEqual(
            manga.mal_url, "https://myanimelist.net/manga/1/Mapped"
        )
        self.assertEqual(manga.image_url, "https://example.test/large.jpg")
        self.assertEqual(manga.legacy_genres, ["Drama"])
        self.assertEqual(
            manga.genres_detailed,
            ["drama", "school", "seinen"],
        )
        self.assertEqual(
            [link.genre.name for link in manga.genre_links],
            ["Drama"],
        )
        self.assertIsNotNone(manga.last_jikan_sync)

    def test_publication_year_uses_nested_year_then_iso_fallback(self):
        self.assertEqual(
            _publication_year(
                {
                    "published": {
                        "from": "2005-07-01T00:00:00+00:00",
                        "prop": {"from": {"year": 2006}},
                    }
                }
            ),
            2006,
        )
        self.assertEqual(
            _publication_year(
                {
                    "published": {
                        "from": "2005-07-01T00:00:00+00:00",
                        "prop": {"from": {"year": None}},
                    }
                }
            ),
            2005,
        )
        self.assertIsNone(_publication_year({"published": None}))

    def test_adult_classification_is_defensive_without_overfiltering(self):
        restricted = (
            {"genres": [{"name": "Hentai"}]},
            {"genres": [{"name": "Erotica"}]},
            {"explicit_genres": [{"name": " erotica "}]},
            {"themes": [{"name": "HENTAI"}]},
            {"rating": "Rx - Hentai"},
        )
        for payload in restricted:
            with self.subTest(payload=payload):
                self.assertTrue(is_adult_content(payload))

        allowed = (
            {"genres": [{"name": "Ecchi"}]},
            {"themes": [{"name": "Adult Cast"}]},
            {"demographics": [{"name": "Seinen"}]},
            {},
        )
        for payload in allowed:
            with self.subTest(payload=payload):
                self.assertFalse(is_adult_content(payload))


class MangaPageSyncTests(unittest.TestCase):
    def test_page_inserts_updates_and_deletes_adult_records_atomically(self):
        existing = manga_record(mal_id=1, title="Old title")
        adult = manga_record(mal_id=3, title="Adult title")
        state = SimpleNamespace(
            next_page=1,
            last_attempt_at=None,
            last_completed_at=None,
            last_error="old failure",
        )
        page = JikanMangaPage(
            entries=[
                {
                    "mal_id": 1,
                    "type": "Manga",
                    "title": "Updated title",
                    "genres": [],
                },
                {
                    "mal_id": 2,
                    "type": "Manga",
                    "title": "Inserted title",
                    "genres": [],
                },
                {
                    "mal_id": 3,
                    "type": "Manga",
                    "title": "Adult title",
                    "genres": [{"name": "Erotica"}],
                },
                {
                    "mal_id": 4,
                    "type": "Manhwa",
                    "title": "Wrong scan type",
                },
                {
                    "mal_id": 5,
                    "type": "Novel",
                    "title": "Unsupported publication type",
                },
                {"mal_id": 0, "title": "Invalid ID"},
            ],
            page=4,
            has_next_page=True,
            last_visible_page=10,
        )

        with (
            patch("backend.jobs.manga_etl.db") as mock_db,
            patch("backend.jobs.manga_etl._sync_state", return_value=state),
        ):
            mock_db.session.scalars.side_effect = [[existing, adult], []]

            result = _apply_manga_page(
                page,
                provider_type="manga",
                state_key="bulk:catalogue:manga:v1",
            )

        self.assertEqual(result.saved, 2)
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.removed_adult, 1)
        self.assertEqual(result.skipped, 4)
        self.assertEqual(existing.title, "Updated title")
        mock_db.session.delete.assert_called_once_with(adult)
        inserted = [
            call.args[0]
            for call in mock_db.session.add.call_args_list
            if isinstance(call.args[0], Manga)
        ]
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0].mal_id, 2)
        self.assertEqual(inserted[0].content_type, "MANGA")
        self.assertEqual(state.next_page, 5)
        self.assertIsNone(state.last_error)
        mock_db.session.commit.assert_called_once()

    def test_catalogue_uses_independent_manga_and_manhwa_cursors(self):
        scan_results = [
            MangaTypeSyncResult(inserted=1),
            MangaTypeSyncResult(inserted=2),
        ]
        with patch(
            "backend.jobs.manga_etl._sync_manga_type",
            side_effect=scan_results,
        ) as sync_type:
            result = sync_manga_catalogue(max_pages=7)

        self.assertEqual(sync_type.call_count, len(MANGA_PROVIDER_TYPES))
        for provider_type, call in zip(
            MANGA_PROVIDER_TYPES,
            sync_type.call_args_list,
            strict=True,
        ):
            self.assertEqual(call.kwargs["provider_type"], provider_type)
            self.assertEqual(
                call.kwargs["state_key"],
                MANGA_STATE_KEYS[provider_type],
            )
            self.assertEqual(call.kwargs["max_pages"], 7)
        self.assertEqual(result.inserted, 3)

    def test_rate_limit_preserves_the_failed_type_cursor(self):
        rate_limit_error = http_error(
            "https://example.test/manga?type=manhwa&page=12",
            429,
        )
        self.addCleanup(rate_limit_error.close)

        def rate_limited(*, manga_type, page):
            self.assertEqual((manga_type, page), ("manhwa", 12))
            raise rate_limit_error

        with (
            patch("backend.jobs.manga_etl.ensure_anime_schema"),
            patch("backend.jobs.manga_etl._next_page", return_value=12),
            patch("backend.jobs.manga_etl._record_page_error") as record_error,
        ):
            result = _sync_manga_type(
                provider_type="manhwa",
                state_key=MANGA_STATE_KEYS["manhwa"],
                fetch_page=rate_limited,
            )

        self.assertEqual(result.pages_attempted, 1)
        self.assertEqual(result.pages_completed, 0)
        self.assertEqual(result.pages_failed, 1)
        self.assertEqual(result.next_page, 12)
        record_error.assert_called_once()
        self.assertEqual(
            record_error.call_args.args[:2],
            (MANGA_STATE_KEYS["manhwa"], 12),
        )

    def test_temporary_failures_preserve_cursor_after_bounded_retries(self):
        def unavailable(*, manga_type, page):
            raise JikanTemporaryError(
                f"{manga_type} page {page} temporarily unavailable"
            )

        with (
            patch("backend.jobs.manga_etl.ensure_anime_schema"),
            patch("backend.jobs.manga_etl._next_page", return_value=8),
            patch("backend.jobs.manga_etl._record_page_error") as record_error,
        ):
            result = _sync_manga_type(
                provider_type="manga",
                state_key=MANGA_STATE_KEYS["manga"],
                max_pages=5,
                max_consecutive_failures=2,
                fetch_page=unavailable,
            )

        self.assertEqual(result.pages_attempted, 2)
        self.assertEqual(result.pages_failed, 2)
        self.assertEqual(result.next_page, 8)
        self.assertEqual(record_error.call_count, 2)
        self.assertTrue(
            all(call.args[1] == 8 for call in record_error.call_args_list)
        )

    def test_provider_page_cap_wraps_cursor_for_the_next_refresh_cycle(self):
        capped_page = JikanMangaPage(
            entries=[{"mal_id": 1, "type": "Manga", "title": "Example"}],
            page=1000,
            has_next_page=True,
            last_visible_page=1001,
        )
        with (
            patch("backend.jobs.manga_etl.ensure_anime_schema"),
            patch("backend.jobs.manga_etl._next_page", return_value=1000),
            patch(
                "backend.jobs.manga_etl._apply_manga_page",
                return_value=MangaPageApplyResult(saved=1),
            ),
            patch("backend.jobs.manga_etl._record_page_error") as record_error,
        ):
            result = _sync_manga_type(
                provider_type="manga",
                state_key=MANGA_STATE_KEYS["manga"],
                max_pages=1,
                fetch_page=lambda **_kwargs: capped_page,
            )

        self.assertTrue(result.complete)
        self.assertTrue(result.provider_page_limit_exceeded)
        self.assertEqual(result.next_page, 1)
        self.assertEqual(
            record_error.call_args.args[:2],
            (MANGA_STATE_KEYS["manga"], 1),
        )


class MangaRefreshTests(unittest.TestCase):
    def test_refresh_queue_updates_deletes_and_classifies_failures(self):
        records = [manga_record(mal_id=mal_id) for mal_id in range(1, 8)]
        not_found_error = http_error("https://example.test/manga/3", 404)
        self.addCleanup(not_found_error.close)

        def fetch_manga(mal_id):
            if mal_id == 1:
                return {
                    "data": {
                        "mal_id": 1,
                        "type": "Manga",
                        "title": "Fresh title",
                        "genres": [],
                    }
                }
            if mal_id == 2:
                return {
                    "data": {
                        "mal_id": 2,
                        "type": "Manga",
                        "genres": [{"name": "Hentai"}],
                    }
                }
            if mal_id == 3:
                raise not_found_error
            if mal_id == 4:
                raise JikanTemporaryError("provider unavailable")
            if mal_id == 5:
                return {"data": []}
            if mal_id == 6:
                return {
                    "data": {
                        "mal_id": 600,
                        "type": "Manga",
                        "title": "Wrong cached record",
                    }
                }
            return {
                "data": {
                    "mal_id": 7,
                    "type": "Novel",
                    "title": "Unsupported publication",
                }
            }

        with (
            patch("backend.jobs.manga_etl.ensure_anime_schema"),
            patch("backend.jobs.manga_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [records, []]

            result = refresh_manga_catalogue(
                limit=7,
                batch_size=2,
                fetch_manga=fetch_manga,
            )

        self.assertEqual(result.selected, 7)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.removed_adult, 1)
        self.assertEqual(result.removed_unsupported, 1)
        self.assertEqual(result.not_found, 1)
        self.assertEqual(result.temporary_errors, 1)
        self.assertEqual(result.invalid_payloads, 2)
        self.assertEqual(records[0].title, "Fresh title")
        self.assertEqual(
            [call.args[0] for call in mock_db.session.delete.call_args_list],
            [records[1], records[6]],
        )
        self.assertTrue(
            all(record.last_jikan_attempt is not None for record in records)
        )
        self.assertEqual(mock_db.session.commit.call_count, 4)


if __name__ == "__main__":
    unittest.main()

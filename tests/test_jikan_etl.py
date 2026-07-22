import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.jobs.jikan_etl import (
    _detailed_genres,
    _fetch_anime_data,
    _names,
    _season,
    _update_anime,
    _valid_score,
    backfill_missing_seasons,
    refresh_catalogue,
    sync_season,
)
from backend.models import Anime
from backend.services.jikan_client import JikanTemporaryError


class JikanEtlTests(unittest.TestCase):
    def test_extracts_unique_genre_names(self):
        self.assertEqual(
            _names([{"name": "Action"}, {"name": "Action"}, {"name": " Drama "}]),
            ["Action", "Drama"],
        )

    def test_preserves_existing_detailed_tags_and_adds_jikan_categories(self):
        data = {
            "genres": [{"name": "Action"}],
            "themes": [{"name": "School"}],
            "demographics": [{"name": "Shounen"}],
        }

        self.assertEqual(
            _detailed_genres(data, ["existing tag", "action"]),
            ["existing tag", "action", "school", "shounen"],
        )

    def test_treats_jikan_zero_as_an_unknown_score(self):
        self.assertEqual(_valid_score(8.25), 8.25)
        self.assertIsNone(_valid_score(0))
        self.assertIsNone(_valid_score(None))

    def test_normalizes_jikan_seasons(self):
        self.assertEqual(_season(" Winter "), "winter")
        self.assertEqual(_season("summer"), "summer")
        self.assertIsNone(_season("monsoon"))
        self.assertIsNone(_season(None))

    def test_updates_anime_season_from_jikan(self):
        anime = Anime(
            animeID=1,
            mal_id=1,
            title="Example",
            alternative_title=None,
            type="TV",
            season="summer",
            year=2020,
            score=8.0,
            episodes=12,
            mal_url="https://example.com",
            sequel=False,
            image_url="",
            legacy_genres=[],
            genres_detailed=[],
        )

        _update_anime(anime, {"season": "Fall", "genres": []}, {})

        self.assertEqual(anime.season, "fall")

    def test_returns_valid_jikan_anime_data(self):
        data = {"mal_id": 1, "title": "Cowboy Bebop"}

        self.assertEqual(_fetch_anime_data(1, lambda _mal_id: {"data": data}), data)

    def test_skips_temporary_errors_and_invalid_payloads(self):
        def temporary_failure(_mal_id: int):
            raise JikanTemporaryError("Jikan is unavailable")

        self.assertIsNone(_fetch_anime_data(1, temporary_failure))
        self.assertIsNone(_fetch_anime_data(1, lambda _mal_id: {"data": []}))

    def test_skipped_records_are_marked_attempted_to_advance_queue(self):
        records = [
            SimpleNamespace(animeID=1, mal_id=1),
            SimpleNamespace(animeID=2, mal_id=2),
        ]

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [records, []]

            updated, skipped = refresh_catalogue(
                limit=2,
                batch_size=1,
                fetch_anime=lambda _mal_id: {"data": []},
            )

        self.assertEqual((updated, skipped), (0, 2))
        self.assertEqual(mock_db.session.execute.call_count, 2)
        self.assertGreaterEqual(mock_db.session.commit.call_count, 3)

    def test_season_sync_reuses_listing_data_without_refetching_titles(self):
        anime = SimpleNamespace(mal_id=1)
        seasonal_data = {"mal_id": 1, "title": "Example", "season": "summer"}

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._update_anime") as update_anime,
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            saved, skipped = sync_season(
                2026,
                "summer",
                fetch_season=lambda _year, _season: [seasonal_data],
            )

        self.assertEqual((saved, skipped), (1, 0))
        update_anime.assert_called_once_with(anime, seasonal_data, {})

    def test_backfill_rejects_invalid_year_limit(self):
        with self.assertRaises(ValueError):
            backfill_missing_seasons(year_limit=0)

    def test_failed_season_year_is_marked_attempted_to_advance_queue(self):
        def unavailable(_year: int | None, _season: str | None):
            raise JikanTemporaryError("Jikan is unavailable")

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._pending_season_years", return_value=[2025]),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            result = backfill_missing_seasons(fetch_season=unavailable)

        self.assertEqual(result, (0, 0, 1))
        mock_db.session.execute.assert_called_once()
        mock_db.session.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()

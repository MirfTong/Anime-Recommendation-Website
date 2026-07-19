import unittest

from backend.jobs.jikan_etl import (
    _detailed_genres,
    _fetch_anime_data,
    _names,
    _valid_score,
)
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

    def test_returns_valid_jikan_anime_data(self):
        data = {"mal_id": 1, "title": "Cowboy Bebop"}

        self.assertEqual(_fetch_anime_data(1, lambda _mal_id: {"data": data}), data)

    def test_skips_temporary_errors_and_invalid_payloads(self):
        def temporary_failure(_mal_id: int):
            raise JikanTemporaryError("Jikan is unavailable")

        self.assertIsNone(_fetch_anime_data(1, temporary_failure))
        self.assertIsNone(_fetch_anime_data(1, lambda _mal_id: {"data": []}))


if __name__ == "__main__":
    unittest.main()

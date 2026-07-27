import unittest
from unittest.mock import patch

from sqlalchemy import select

from backend.app import _anime_statement, _normalized_type, app
from backend.models import Anime, db


class AppTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_anime_list_returns_paginated_json(self):
        response = self.client.get("/api/v1/anime?min_year=2020&per_page=2")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["pagination"]["per_page"], 2)
        self.assertGreaterEqual(body["items"][0]["year"], 2020)

    def test_anime_detail_returns_detailed_tags(self):
        response = self.client.get("/api/v1/anime/52991")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["item"]["mal_id"], 52991)
        self.assertIn("season", body["item"])
        self.assertIn("synopsis", body["item"])
        self.assertIn("genres_detailed", body["item"])

    def test_anime_list_accepts_a_season_filter(self):
        response = self.client.get("/api/v1/anime?season=winter&per_page=2")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(item["season"] == "winter" for item in body["items"]))

    def test_type_filter_values_are_normalized(self):
        self.assertEqual(_normalized_type("Movie"), "MOVIE")
        self.assertEqual(_normalized_type("tv_special"), "SPECIAL")

    def test_public_api_excludes_hentai_records_and_filter_options(self):
        anime_response = self.client.get(
            "/api/v1/anime", query_string={"genre": "Hentai"}
        )
        genre_response = self.client.get("/api/v1/genres")
        tag_response = self.client.get(
            "/api/v1/tags", query_string={"q": "hentai"}
        )

        self.assertEqual(anime_response.status_code, 200)
        self.assertEqual(anime_response.get_json()["items"], [])
        self.assertFalse(
            any(
                name.strip().casefold() == "hentai"
                for name in genre_response.get_json()["items"]
            )
        )
        self.assertFalse(
            any(
                name.strip().casefold() == "hentai"
                for name in tag_response.get_json()["items"]
            )
        )

    def test_public_query_checks_every_stored_genre_representation(self):
        sql = str(_anime_statement()).lower()

        self.assertIn("genre.name", sql)
        self.assertIn("unnest(anime.genres)", sql)
        self.assertIn("unnest(anime.genres_detailed)", sql)
        self.assertGreaterEqual(sql.count("lower(trim("), 3)

    def test_detailed_tag_catalogue_supports_search(self):
        response = self.client.get("/api/v1/genres")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", body)
        tag_response = self.client.get("/api/v1/tags?limit=1")
        self.assertEqual(tag_response.status_code, 200)
        tags = tag_response.get_json()["items"]
        self.assertIsInstance(tags, list)
        if tags:
            search_response = self.client.get(
                "/api/v1/tags", query_string={"q": tags[0][:3], "limit": 50}
            )
            self.assertEqual(search_response.status_code, 200)
            self.assertIn(tags[0], search_response.get_json()["items"])

    def test_anime_list_accepts_a_detailed_tag_filter(self):
        catalogue = self.client.get("/api/v1/tags?limit=1").get_json()
        if not catalogue["items"]:
            self.skipTest("The test catalogue does not contain detailed tags")
        tag = catalogue["items"][0]

        response = self.client.get("/api/v1/anime", query_string={"tag": tag})
        body = response.get_json()

        self.assertEqual(response.status_code, 200)
        mal_ids = [item["mal_id"] for item in body["items"]]
        with app.app_context():
            matching_anime = db.session.scalars(
                select(Anime).where(Anime.mal_id.in_(mal_ids))
            ).all()
        self.assertTrue(all(tag in anime.genres_detailed for anime in matching_anime))

    def test_popular_current_season_returns_a_limited_seasonal_list(self):
        with patch("backend.app._current_season_identity", return_value=(2026, "summer")):
            response = self.client.get("/api/v1/anime/seasonal?limit=6")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["season"], "summer")
        self.assertEqual(body["year"], 2026)
        self.assertLessEqual(len(body["items"]), 6)
        self.assertEqual(body["pagination"]["page"], 1)
        self.assertEqual(body["pagination"]["per_page"], 6)
        self.assertGreaterEqual(body["pagination"]["total"], len(body["items"]))
        self.assertTrue(
            all(item["season"] == "summer" and item["year"] == 2026 for item in body["items"])
        )

    def test_popular_current_season_supports_pagination(self):
        with patch("backend.app._current_season_identity", return_value=(2026, "summer")):
            response = self.client.get("/api/v1/anime/seasonal?limit=6&page=2")

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["pagination"]["page"], 2)
        self.assertEqual(body["pagination"]["per_page"], 6)

    def test_invalid_filter_returns_json_error(self):
        response = self.client.get("/api/v1/anime?min_score=20")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_invalid_season_returns_json_error(self):
        response = self.client.get("/api/v1/anime?season=monsoon")

        self.assertEqual(response.status_code, 400)
        self.assertIn("season must be", response.get_json()["error"]["message"])

    def test_unknown_anime_returns_json_404(self):
        response = self.client.get("/api/v1/anime/999999999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["message"], "Anime not found")


if __name__ == "__main__":
    unittest.main()

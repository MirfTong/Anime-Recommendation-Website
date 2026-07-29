import unittest
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from backend.app import (
    _anime_statement,
    _catalogue_rows_subquery,
    _filtered_anime_statement,
    _filtered_manga_statement,
    _manga_statement,
    _normalized_content_type,
    _normalized_status,
    _normalized_type,
    _ordered_catalogue_rows,
    _request_filter_signature,
    _serialize_manga,
    app,
    response_cache,
)
from backend.models import Anime, Manga, db


class AppTests(unittest.TestCase):
    def setUp(self):
        response_cache.clear()
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

    def test_catalogue_supports_database_ordered_sort_options(self):
        expectations = {
            "top_rated": ("score", True),
            "newest": ("year", True),
            "oldest": ("year", False),
            "most_episodes": ("episodes", True),
        }
        for sort, (field, reverse) in expectations.items():
            with self.subTest(sort=sort):
                response = self.client.get(
                    "/api/v1/catalogue",
                    query_string={
                        "content_type": "ANIME",
                        "sort": sort,
                        "per_page": 8,
                    },
                )
                self.assertEqual(response.status_code, 200)
                values = [
                    item[field]
                    for item in response.get_json()["items"]
                    if item[field] is not None
                ]
                self.assertEqual(values, sorted(values, reverse=reverse))

        title_response = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "MANGA",
                "sort": "title",
                "per_page": 8,
            },
        )
        repeated_title_response = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "MANGA",
                "sort": "title",
                "per_page": 8,
            },
        )
        self.assertEqual(title_response.status_code, 200)
        self.assertEqual(
            title_response.get_json()["items"],
            repeated_title_response.get_json()["items"],
        )
        with app.test_request_context(
            "/api/v1/catalogue?content_type=MANGA&sort=title"
        ):
            catalogue_rows = _catalogue_rows_subquery({"MANGA"})
            title_sql = str(
                _ordered_catalogue_rows(catalogue_rows, "title").compile(
                    dialect=postgresql.dialect()
                )
            ).lower()
        self.assertIn("order by lower(catalogue_rows.title)", title_sql)

    def test_sort_options_are_validated_for_the_selected_content(self):
        anime_response = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "ANIME",
                "sort": "most_chapters",
            },
        )
        mixed_response = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "ALL",
                "sort": "most_episodes",
            },
        )

        self.assertEqual(anime_response.status_code, 400)
        self.assertEqual(mixed_response.status_code, 400)

    def test_catalogue_exposes_freshness_only_from_available_sync_data(self):
        response = self.client.get(
            "/api/v1/catalogue",
            query_string={"content_type": "ANIME", "per_page": 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("updated_at", response.get_json())

    def test_anime_maximum_episode_filter_supports_short_series(self):
        response = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "ANIME",
                "max_episodes": 13,
                "per_page": 8,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            all(
                item["episodes"] is not None and item["episodes"] <= 13
                for item in response.get_json()["items"]
            )
        )

    def test_type_filter_values_are_normalized(self):
        self.assertEqual(_normalized_type("Movie"), "MOVIE")
        self.assertEqual(_normalized_type("tv_special"), "SPECIAL")

    def test_readable_catalogue_filter_values_are_normalized(self):
        self.assertEqual(_normalized_content_type(" manhwa "), "MANHWA")
        self.assertEqual(_normalized_status("NOT_YET_PUBLISHED"), "not yet published")

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

    def test_public_anime_query_uses_the_indexed_adult_flag(self):
        sql = str(_anime_statement()).lower()

        self.assertIn("anime.is_adult is false", sql)
        self.assertNotIn("unnest(", sql)
        self.assertNotIn("genre.name", sql)

    def test_manga_public_query_uses_the_indexed_adult_flag(self):
        sql = str(
            _manga_statement({"MANGA", "MANHWA"}).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn("manga.is_adult is false", sql)
        self.assertNotIn("unnest(", sql)
        self.assertNotIn("genre.name", sql)

    def test_catalogue_filters_include_unrated_public_titles(self):
        with app.test_request_context("/api/v1/catalogue?content_type=ANIME"):
            anime_sql = str(_filtered_anime_statement()).lower()
        with app.test_request_context("/api/v1/catalogue?content_type=MANGA"):
            manga_sql = str(_filtered_manga_statement({"MANGA"})).lower()

        self.assertNotIn("anime.score is not null", anime_sql)
        self.assertNotIn("manga.score is not null", manga_sql)

    def test_pagination_pages_share_one_total_count_cache_key(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ANIME&page=1&per_page=24"
            "&genre=Action"
        ):
            first_page = _request_filter_signature(
                exclude={"content_type", "page", "per_page"}
            )
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ANIME&page=7&per_page=48"
            "&genre=Action"
        ):
            later_page = _request_filter_signature(
                exclude={"content_type", "page", "per_page"}
            )

        self.assertEqual(first_page, later_page)

    def test_tag_searches_reuse_one_precomputed_scope(self):
        with patch(
            "backend.app._load_detailed_tag_names",
            return_value=("action", "school", "space"),
        ) as load_tags:
            action = self.client.get(
                "/api/v1/tags?q=act&content_type=ANIME"
            )
            school = self.client.get(
                "/api/v1/tags?q=school&content_type=ANIME"
            )

        self.assertEqual(action.get_json()["items"], ["action"])
        self.assertEqual(school.get_json()["items"], ["school"])
        load_tags.assert_called_once()

    def test_manga_serializer_exposes_print_metadata(self):
        manga = Manga(
            mangaID=9,
            mal_id=42,
            content_type="MANHWA",
            title="Example Manhwa",
            alternative_title="Alternate",
            synopsis="A synopsis.",
            manga_type="Manhwa",
            publication_year=2024,
            status="Publishing",
            score=8.1,
            chapters=50,
            volumes=5,
            mal_url="https://myanimelist.net/manga/42",
            image_url="https://example.test/cover.jpg",
            legacy_genres=[],
            genres_detailed=["school"],
        )

        item = _serialize_manga(manga, detailed=True)

        self.assertEqual(item["content_type"], "MANHWA")
        self.assertEqual(item["publication_year"], 2024)
        self.assertEqual(item["chapters"], 50)
        self.assertEqual(item["volumes"], 5)
        self.assertEqual(item["synopsis"], "A synopsis.")
        self.assertEqual(item["genres_detailed"], ["school"])

    def test_canonical_catalogue_supports_all_content(self):
        response = self.client.get(
            "/api/v1/catalogue",
            query_string={"content_type": "ALL", "per_page": 2},
        )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", body)
        self.assertEqual(body["pagination"]["per_page"], 2)
        self.assertTrue(
            all(
                item["content_type"] in {"ANIME", "MANGA", "MANHWA"}
                for item in body["items"]
            )
        )

    def test_manga_and_manhwa_filters_and_aliases_are_available(self):
        for content_type, alias in (("MANGA", "manga"), ("MANHWA", "manhwa")):
            with self.subTest(content_type=content_type):
                response = self.client.get(
                    "/api/v1/catalogue",
                    query_string={
                        "content_type": content_type,
                        "status": "PUBLISHING",
                        "min_chapters": 1,
                        "min_volumes": 1,
                        "min_score": 1,
                        "min_year": 1900,
                        "genre": "Action",
                        "tag": "school",
                        "per_page": 2,
                    },
                )
                alias_response = self.client.get(
                    f"/api/v1/{alias}", query_string={"per_page": 1}
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(alias_response.status_code, 200)
                self.assertTrue(
                    all(
                        item["content_type"] == content_type
                        for item in response.get_json()["items"]
                    )
                )

    def test_manhwa_filter_query_contains_every_requested_predicate(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=MANHWA&status=PUBLISHING"
            "&min_chapters=25&min_volumes=3&min_score=7&min_year=2000"
            "&max_year=2030&genre=Action&tag=school"
        ):
            statement = _filtered_manga_statement({"MANHWA"})
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn("manga.content_type in ('manhwa')", sql)
        self.assertIn("lower(trim(manga.status)) in ('publishing')", sql)
        self.assertIn("manga.chapters >= 25", sql)
        self.assertIn("manga.volumes >= 3", sql)
        self.assertIn("manga.score >= 7", sql)
        self.assertIn("manga.publication_year >= 2000", sql)
        self.assertIn("manga.publication_year <= 2030", sql)
        self.assertIn("genre.name = 'action'", sql)
        self.assertIn("manga.genres_detailed @> array['school']", sql)

    def test_content_scoped_facets_and_random_endpoint_are_available(self):
        genre_response = self.client.get(
            "/api/v1/genres", query_string={"content_type": "MANHWA"}
        )
        tag_response = self.client.get(
            "/api/v1/tags",
            query_string={"content_type": "MANGA", "q": "school"},
        )
        random_response = self.client.get(
            "/api/v1/catalogue/random",
            query_string={"content_type": "ALL", "limit": 2},
        )

        self.assertEqual(genre_response.status_code, 200)
        self.assertEqual(tag_response.status_code, 200)
        self.assertEqual(random_response.status_code, 200)
        self.assertLessEqual(len(random_response.get_json()["items"]), 2)

    def test_invalid_catalogue_content_type_returns_json_error(self):
        response = self.client.get(
            "/api/v1/catalogue", query_string={"content_type": "NOVEL"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("content_type must be", response.get_json()["error"]["message"])

    def test_unknown_manga_and_manhwa_details_return_json_404(self):
        for content_type in ("MANGA", "MANHWA"):
            with self.subTest(content_type=content_type):
                response = self.client.get(
                    f"/api/v1/catalogue/{content_type}/999999999"
                )
                self.assertEqual(response.status_code, 404)

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

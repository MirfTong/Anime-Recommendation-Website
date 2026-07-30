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
    _normalized_anime_status,
    _normalized_content_type,
    _normalized_status,
    _normalized_type,
    _ordered_catalogue_rows,
    _request_filter_signature,
    _serialize_anime,
    _serialize_manga,
    app,
    response_cache,
)
from backend.models import (
    Anime,
    AnimeStreamingService,
    Manga,
    StreamingService,
    Studio,
    db,
)


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
        self.assertIn("status", body["items"][0])
        self.assertIn("studios", body["items"][0])
        self.assertIn("streaming_services", body["items"][0])

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
        self.assertEqual(
            _normalized_anime_status("Currently Airing"),
            "CURRENTLY_AIRING",
        )

    def test_anime_serializer_exposes_normalized_airing_status(self):
        anime = Anime(
            animeID=12,
            mal_id=24,
            title="Example Anime",
            alternative_title=None,
            synopsis=None,
            type="TV",
            season="summer",
            status="CURRENTLY_AIRING",
            year=2026,
            score=8.0,
            episodes=12,
            mal_url="https://myanimelist.net/anime/24",
            sequel=False,
            image_url="",
            legacy_genres=[],
            genres_detailed=[],
        )

        item = _serialize_anime(anime)

        self.assertEqual(item["status"], "CURRENTLY_AIRING")

    def test_anime_serializer_exposes_sorted_studios_and_streaming_links(self):
        anime = Anime(
            animeID=13,
            mal_id=25,
            title="Relationship Example",
            alternative_title=None,
            synopsis=None,
            type="TV",
            season="summer",
            status="CURRENTLY_AIRING",
            year=2026,
            score=8.0,
            episodes=12,
            mal_url="https://myanimelist.net/anime/25",
            sequel=False,
            image_url="",
            legacy_genres=[],
            genres_detailed=[],
        )
        anime.studio_entries.extend(
            [
                Studio(mal_id=2, name="Zeta Studio", normalized_name="zeta studio"),
                Studio(mal_id=1, name="Alpha Studio", normalized_name="alpha studio"),
            ]
        )
        crunchyroll = StreamingService(
            name="Crunchyroll",
            normalized_name="crunchyroll",
        )
        netflix = StreamingService(name="Netflix", normalized_name="netflix")
        anime.streaming_links.extend(
            [
                AnimeStreamingService(
                    streaming_service=netflix,
                    url="https://example.test/netflix",
                ),
                AnimeStreamingService(
                    streaming_service=crunchyroll,
                    url="https://example.test/crunchyroll",
                ),
            ]
        )

        item = _serialize_anime(anime)

        self.assertEqual(
            item["studios"],
            [
                {"mal_id": 1, "name": "Alpha Studio"},
                {"mal_id": 2, "name": "Zeta Studio"},
            ],
        )
        self.assertEqual(
            item["streaming_services"],
            [
                {
                    "name": "Crunchyroll",
                    "url": "https://example.test/crunchyroll",
                },
                {
                    "name": "Netflix",
                    "url": "https://example.test/netflix",
                },
            ],
        )

    def test_anime_status_filter_uses_canonical_indexed_predicate(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ANIME"
            "&status=Currently%20Airing"
        ):
            statement = _filtered_anime_statement()
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn(
            "anime.status in ('currently_airing')",
            sql,
        )

    def test_anime_studio_and_streaming_filters_use_any_match_exists_predicates(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ANIME"
            "&studio=Studio%20Pierrot&studio=MAPPA"
            "&streaming_service=Crunchyroll"
            "&streaming_service=Netflix"
        ):
            statement = _filtered_anime_statement()
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn("exists", sql)
        self.assertIn("studio.normalized_name in ('studio pierrot', 'mappa')", sql)
        self.assertIn(
            "streaming_service.normalized_name in ('crunchyroll', 'netflix')",
            sql,
        )
        # One IN predicate gives match-any semantics. Repeating one EXISTS per
        # selected value would accidentally require an anime to match all.
        self.assertEqual(sql.count("studio.normalized_name in"), 1)
        self.assertEqual(sql.count("streaming_service.normalized_name in"), 1)

    def test_anime_only_relationship_filters_narrow_mixed_catalogue_results(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ALL&studio=MAPPA"
        ):
            catalogue_rows = _catalogue_rows_subquery(
                {"ANIME", "MANGA", "MANHWA"}
            )
        sql = str(
            select(catalogue_rows).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn("'anime' as content_type", sql)
        self.assertNotIn("from manga", sql)

    def test_streaming_filter_narrows_mixed_catalogue_results_to_anime(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ALL"
            "&streaming_service=Crunchyroll"
        ):
            catalogue_rows = _catalogue_rows_subquery(
                {"ANIME", "MANGA", "MANHWA"}
            )
        sql = str(
            select(catalogue_rows).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertIn("'anime' as content_type", sql)
        self.assertIn("streaming_service.normalized_name", sql)
        self.assertNotIn("from manga", sql)

    def test_print_length_filters_narrow_mixed_catalogue_results_to_print(self):
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ALL"
            "&min_chapters=10&max_chapters=100"
            "&min_volumes=2&max_volumes=12"
        ):
            catalogue_rows = _catalogue_rows_subquery(
                {"ANIME", "MANGA", "MANHWA"}
            )
        sql = str(
            select(catalogue_rows).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()

        self.assertNotIn("from anime", sql)
        self.assertIn("from manga", sql)
        self.assertIn("manga.chapters >= 10", sql)
        self.assertIn("manga.chapters <= 100", sql)
        self.assertIn("manga.volumes >= 2", sql)
        self.assertIn("manga.volumes <= 12", sql)

    def test_anime_and_print_status_semantics_are_kept_separate(self):
        invalid_anime = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "ANIME",
                "status": "PUBLISHING",
            },
        )
        mixed_status = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "ALL",
                "status": "CURRENTLY_AIRING",
            },
        )
        print_status = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "MANGA",
                "status": "FINISHED",
                "per_page": 1,
            },
        )

        self.assertEqual(invalid_anime.status_code, 400)
        self.assertEqual(mixed_status.status_code, 400)
        self.assertEqual(print_status.status_code, 200)

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

    def test_range_predicates_only_exclude_unknown_values_when_active(self):
        with app.test_request_context("/api/v1/catalogue?content_type=ANIME"):
            unrestricted_anime_sql = str(
                _filtered_anime_statement().compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).lower()
        with app.test_request_context(
            "/api/v1/catalogue?content_type=ANIME"
            "&min_year=2000&max_year=2026"
            "&min_episodes=6&max_episodes=24&min_score=7"
        ):
            restricted_anime_sql = str(
                _filtered_anime_statement().compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).lower()
        with app.test_request_context("/api/v1/catalogue?content_type=MANGA"):
            unrestricted_print_sql = str(
                _filtered_manga_statement({"MANGA"}).compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).lower()
        with app.test_request_context(
            "/api/v1/catalogue?content_type=MANGA"
            "&min_chapters=10&max_chapters=100"
            "&min_volumes=2&max_volumes=12"
        ):
            restricted_print_sql = str(
                _filtered_manga_statement({"MANGA"}).compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).lower()

        # With no range predicate, NULL/unknown metadata remains eligible.
        self.assertNotIn("anime.year >=", unrestricted_anime_sql)
        self.assertNotIn("anime.year <=", unrestricted_anime_sql)
        self.assertNotIn("anime.episodes >=", unrestricted_anime_sql)
        self.assertNotIn("anime.episodes <=", unrestricted_anime_sql)
        self.assertNotIn("anime.score >=", unrestricted_anime_sql)
        self.assertNotIn("manga.chapters >=", unrestricted_print_sql)
        self.assertNotIn("manga.chapters <=", unrestricted_print_sql)
        self.assertNotIn("manga.volumes >=", unrestricted_print_sql)
        self.assertNotIn("manga.volumes <=", unrestricted_print_sql)

        # SQL comparisons evaluate to UNKNOWN for NULL, so an active range
        # excludes records whose value cannot be confirmed to match.
        self.assertIn("anime.year >= 2000", restricted_anime_sql)
        self.assertIn("anime.year <= 2026", restricted_anime_sql)
        self.assertIn("anime.episodes >= 6", restricted_anime_sql)
        self.assertIn("anime.episodes <= 24", restricted_anime_sql)
        self.assertIn("anime.score >= 7", restricted_anime_sql)
        self.assertIn("manga.chapters >= 10", restricted_print_sql)
        self.assertIn("manga.chapters <= 100", restricted_print_sql)
        self.assertIn("manga.volumes >= 2", restricted_print_sql)
        self.assertIn("manga.volumes <= 12", restricted_print_sql)

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

    def test_unlimited_tag_and_studio_dropdowns_return_every_cached_option(self):
        with (
            patch(
                "backend.app._load_detailed_tag_names",
                return_value=("action", "school", "space"),
            ),
            patch(
                "backend.app._load_facet_names",
                return_value=("Bones", "MAPPA", "Studio Pierrot"),
            ),
        ):
            tags = self.client.get("/api/v1/tags")
            studios = self.client.get("/api/v1/studios")
            limited_tags = self.client.get("/api/v1/tags?limit=1")

        self.assertEqual(tags.get_json()["items"], ["action", "school", "space"])
        self.assertEqual(
            studios.get_json()["items"],
            ["Bones", "MAPPA", "Studio Pierrot"],
        )
        self.assertEqual(limited_tags.get_json()["items"], ["action"])

    def test_studio_and_streaming_searches_reuse_precomputed_facets(self):
        def load_facets(_content_types, facet_type):
            if facet_type == "studio":
                return ("Bones", "MAPPA", "Studio Pierrot")
            return ("Crunchyroll", "Netflix")

        with patch(
            "backend.app._load_facet_names",
            side_effect=load_facets,
        ) as load_options:
            mappa = self.client.get("/api/v1/studios?q=map")
            pierrot = self.client.get("/api/v1/studios?q=pier")
            netflix = self.client.get("/api/v1/streaming-services?q=net")

        self.assertEqual(mappa.get_json()["items"], ["MAPPA"])
        self.assertEqual(pierrot.get_json()["items"], ["Studio Pierrot"])
        self.assertEqual(netflix.get_json()["items"], ["Netflix"])
        self.assertEqual(load_options.call_count, 2)

    def test_filter_range_endpoint_returns_content_appropriate_bounds(self):
        anime = self.client.get(
            "/api/v1/filter-ranges",
            query_string={"content_type": "ANIME"},
        )
        manga = self.client.get(
            "/api/v1/filter-ranges",
            query_string={"content_type": "MANGA"},
        )
        mixed = self.client.get(
            "/api/v1/filter-ranges",
            query_string={"content_type": "ALL"},
        )

        self.assertEqual(anime.status_code, 200)
        self.assertIsNotNone(anime.get_json()["ranges"]["episodes"])
        self.assertIsNone(anime.get_json()["ranges"]["chapters"])
        self.assertEqual(manga.status_code, 200)
        self.assertIsNotNone(manga.get_json()["ranges"]["chapters"])
        self.assertIsNotNone(manga.get_json()["ranges"]["volumes"])
        self.assertIsNone(manga.get_json()["ranges"]["episodes"])
        self.assertEqual(mixed.status_code, 200)
        self.assertIsNotNone(mixed.get_json()["ranges"]["year"])
        self.assertIsNotNone(mixed.get_json()["ranges"]["score"])

    def test_filter_range_endpoint_reuses_one_cached_scope(self):
        ranges = {
            "year": {"min": 2000, "max": 2026},
            "score": {"min": 1.0, "max": 10.0},
            "episodes": {"min": 1, "max": 1000},
            "chapters": None,
            "volumes": None,
        }
        with patch(
            "backend.app._load_filter_ranges",
            return_value=ranges,
        ) as load_ranges:
            first = self.client.get(
                "/api/v1/filter-ranges",
                query_string={"content_type": "ANIME"},
            )
            second = self.client.get(
                "/api/v1/filter-ranges",
                query_string={"content_type": "ANIME"},
            )

        self.assertEqual(first.get_json()["ranges"], ranges)
        self.assertEqual(second.get_json()["ranges"], ranges)
        load_ranges.assert_called_once()

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
            "&min_chapters=25&max_chapters=250"
            "&min_volumes=3&max_volumes=30&min_score=7&min_year=2000"
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
        self.assertIn("manga.chapters <= 250", sql)
        self.assertIn("manga.volumes >= 3", sql)
        self.assertIn("manga.volumes <= 30", sql)
        self.assertIn("manga.score >= 7", sql)
        self.assertIn("manga.publication_year >= 2000", sql)
        self.assertIn("manga.publication_year <= 2030", sql)
        self.assertIn("genre.name = 'action'", sql)
        self.assertIn("manga.genres_detailed @> array['school']", sql)

    def test_manga_range_filters_reject_reversed_bounds(self):
        chapters = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "MANGA",
                "min_chapters": 100,
                "max_chapters": 10,
            },
        )
        volumes = self.client.get(
            "/api/v1/catalogue",
            query_string={
                "content_type": "MANHWA",
                "min_volumes": 20,
                "max_volumes": 2,
            },
        )

        self.assertEqual(chapters.status_code, 400)
        self.assertIn(
            "min_chapters cannot be greater than max_chapters",
            chapters.get_json()["error"]["message"],
        )
        self.assertEqual(volumes.status_code, 400)
        self.assertIn(
            "min_volumes cannot be greater than max_volumes",
            volumes.get_json()["error"]["message"],
        )

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

    def test_anime_random_endpoint_applies_relationship_filters(self):
        response = self.client.get(
            "/api/v1/anime/random",
            query_string={
                "studio": "Studio That Cannot Exist 4d27dc9f",
                "limit": 2,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"], [])

    def test_anime_routes_expose_studio_and_streaming_fields(self):
        routes = (
            "/api/v1/anime?per_page=1",
            "/api/v1/anime/random?limit=1",
            "/api/v1/catalogue?content_type=ALL&max_episodes=10000&per_page=1",
            "/api/v1/catalogue/random?content_type=ALL"
            "&max_episodes=10000&limit=1",
            "/api/v1/anime/52991",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                body = response.get_json()
                self.assertEqual(response.status_code, 200)
                entries = body.get("items") or [body.get("item")]
                self.assertTrue(entries)
                self.assertIsNotNone(entries[0])
                self.assertEqual(entries[0]["content_type"], "ANIME")
                self.assertIn("studios", entries[0])
                self.assertIn("streaming_services", entries[0])

        with patch(
            "backend.app._current_season_identity",
            return_value=(2026, "summer"),
        ):
            seasonal = self.client.get("/api/v1/anime/seasonal?limit=1")
        seasonal_body = seasonal.get_json()
        self.assertEqual(seasonal.status_code, 200)
        self.assertTrue(seasonal_body["items"])
        self.assertIn("studios", seasonal_body["items"][0])
        self.assertIn("streaming_services", seasonal_body["items"][0])

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

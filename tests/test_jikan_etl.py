import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from backend.jobs.jikan_etl import (
    BulkSeasonSyncResult,
    CatalogueRefreshResult,
    CurrentSeasonSyncResult,
    SUPPLEMENTAL_PROVIDER_TYPES,
    SUPPLEMENTAL_STATE_KEYS,
    SeasonPageApplyResult,
    SeasonBackfillResult,
    SeasonCoverage,
    SupplementalCatalogueSyncResult,
    _apply_season_page,
    _anime_status,
    _anime_type,
    _detailed_genres,
    _current_season_identity,
    _fetch_anime_data,
    _is_hentai,
    _names,
    _new_anime,
    _prepared_season_entry,
    _season,
    _season_from_air_date,
    _update_anime,
    _valid_score,
    backfill_missing_seasons,
    refresh_catalogue,
    remove_hentai_anime,
    run_scheduled_sync,
    sync_bulk_anime_seasons,
    sync_current_season,
    sync_season,
    sync_supplemental_anime_types,
)
from backend.models import Anime
from backend.jobs.manga_etl import (
    MangaCatalogueSyncResult,
    MangaRefreshResult,
    MangaTypeSyncResult,
)
from backend.services.jikan_client import (
    JikanAnimePage,
    JikanSeasonPage,
    JikanTemporaryError,
)


def anime_record(
    *,
    anime_type="TV",
    season="summer",
    status="FINISHED_AIRING",
):
    return Anime(
        animeID=1,
        mal_id=1,
        title="Example",
        alternative_title=None,
        synopsis=None,
        type=anime_type,
        season=season,
        status=status,
        year=2020,
        score=8.0,
        episodes=12,
        mal_url="https://example.com",
        sequel=False,
        image_url="",
        legacy_genres=[],
        genres_detailed=[],
    )


class JikanEtlTests(unittest.TestCase):
    def test_extracts_unique_genre_names(self):
        self.assertEqual(
            _names([{"name": "Action"}, {"name": "Action"}, {"name": " Drama "}]),
            ["Action", "Drama"],
        )

    def test_ignores_malformed_genre_entries(self):
        self.assertEqual(
            _names([None, "Action", {"name": None}, {"name": " Drama "}]),
            ["Drama"],
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

    def test_normalizes_provider_and_legacy_anime_types(self):
        self.assertEqual(_anime_type("Movie"), "MOVIE")
        self.assertEqual(_anime_type("tv_special"), "SPECIAL")
        self.assertEqual(_anime_type(" TV Special "), "SPECIAL")

    def test_normalizes_supported_jikan_airing_statuses(self):
        self.assertEqual(_anime_status("Currently Airing"), "CURRENTLY_AIRING")
        self.assertEqual(_anime_status("Finished Airing"), "FINISHED_AIRING")
        self.assertEqual(_anime_status("Not yet aired"), "NOT_YET_AIRED")
        self.assertIsNone(_anime_status("Cancelled"))
        self.assertIsNone(_anime_status(None))

    def test_detects_hentai_from_categories_or_rating(self):
        self.assertTrue(
            _is_hentai({"explicit_genres": [{"name": " HENTAI "}]})
        )
        self.assertTrue(_is_hentai({"rating": "Rx - Hentai"}))
        self.assertTrue(_is_hentai({"genres": [{"name": " Erotica "}]}))
        self.assertFalse(
            _is_hentai(
                {
                    "genres": [{"name": "Ecchi"}],
                    "rating": "R+ - Mild Nudity",
                }
            )
        )

    def test_anime_mapping_maintains_the_indexed_adult_flag(self):
        anime = anime_record()

        _update_anime(anime, {"rating": "Rx - Hentai", "genres": []}, {})
        self.assertTrue(anime.is_adult)

        _update_anime(anime, {"rating": "PG-13", "genres": []}, {})
        self.assertFalse(anime.is_adult)

    def test_updates_anime_season_from_jikan(self):
        anime = anime_record()
        _update_anime(anime, {"season": "Fall", "genres": []}, {})
        self.assertEqual(anime.season, "fall")

    def test_updates_anime_status_without_erasing_valid_sparse_data(self):
        anime = anime_record(status="FINISHED_AIRING")

        _update_anime(
            anime,
            {"status": "Currently Airing", "genres": []},
            {},
        )
        self.assertEqual(anime.status, "CURRENTLY_AIRING")

        _update_anime(anime, {"genres": []}, {})
        self.assertEqual(anime.status, "CURRENTLY_AIRING")

        _update_anime(anime, {"status": {"bad": "value"}, "genres": []}, {})
        self.assertEqual(anime.status, "CURRENTLY_AIRING")

    def test_new_anime_stores_normalized_status_or_null(self):
        airing = _new_anime(
            {
                "mal_id": 10,
                "title": "Airing",
                "type": "TV",
                "status": "Currently Airing",
            }
        )
        unknown = _new_anime(
            {
                "mal_id": 11,
                "title": "Unknown",
                "type": "TV",
                "status": "Cancelled",
            }
        )

        self.assertEqual(airing.status, "CURRENTLY_AIRING")
        self.assertIsNone(unknown.status)

    def test_updates_anime_synopsis_from_jikan_detail_payload(self):
        anime = anime_record()
        _update_anime(anime, {"synopsis": "  A new synopsis.  ", "genres": []}, {})

        self.assertEqual(anime.synopsis, "A new synopsis.")

    def test_infers_missing_tv_season_from_premiere_date(self):
        anime = anime_record(season=None)
        _update_anime(
            anime,
            {
                "type": "TV",
                "season": None,
                "aired": {"from": "2020-10-03T00:00:00+00:00"},
                "genres": [],
            },
            {},
        )
        self.assertEqual(anime.season, "fall")
        self.assertEqual(
            _season_from_air_date({"aired": {"prop": {"from": {"month": 4}}}}),
            "spring",
        )

    def test_explicit_unrated_payload_clears_stale_score_and_episode_count(self):
        anime = anime_record()
        _update_anime(anime, {"score": 0, "episodes": None, "genres": []}, {})
        self.assertIsNone(anime.score)
        self.assertIsNone(anime.episodes)

    def test_update_tolerates_malformed_nested_provider_fields(self):
        anime = anime_record()
        _update_anime(
            anime,
            {
                "images": [],
                "relations": [None, "invalid", {"relation": "Sequel"}],
                "genres": [None, {"name": None}],
                "themes": "invalid",
            },
            {},
        )
        self.assertTrue(anime.sequel)
        self.assertEqual(anime.image_url, "")

    def test_sparse_tv_payload_does_not_erase_existing_season(self):
        anime = anime_record(season="spring")
        _update_anime(anime, {"type": "TV", "season": None, "genres": []}, {})
        self.assertEqual(anime.season, "spring")

    def test_non_tv_payload_clears_stale_season(self):
        anime = anime_record(anime_type="Movie", season="spring")
        _update_anime(anime, {"type": "Movie", "season": None, "genres": []}, {})
        self.assertIsNone(anime.season)

    def test_named_listing_forces_season_only_for_tv(self):
        tv = _prepared_season_entry({"mal_id": 1, "type": "TV"}, 2025, "winter")
        movie = _prepared_season_entry({"mal_id": 2, "type": "Movie"}, 2025, "winter")
        self.assertEqual(tv["season"], "winter")
        self.assertNotIn("season", movie)

    def test_current_season_uses_japan_calendar_at_year_boundary(self):
        self.assertEqual(
            _current_season_identity(datetime(2026, 12, 31, 18, tzinfo=timezone.utc)),
            (2027, "winter"),
        )

    def test_classifies_jikan_fetch_failures(self):
        data = {"mal_id": 1, "title": "Cowboy Bebop"}
        self.assertEqual(
            _fetch_anime_data(1, lambda _mal_id: {"data": data}).data,
            data,
        )

        def temporary_failure(_mal_id: int):
            raise JikanTemporaryError("Jikan is unavailable")

        self.assertEqual(_fetch_anime_data(1, temporary_failure).failure, "temporary")
        self.assertEqual(
            _fetch_anime_data(1, lambda _mal_id: {"data": []}).failure,
            "invalid_payload",
        )

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
            result = refresh_catalogue(
                limit=2,
                batch_size=1,
                fetch_anime=lambda _mal_id: {"data": []},
            )

        self.assertEqual(result.selected, 2)
        self.assertEqual(result.invalid_payloads, 2)
        self.assertEqual(mock_db.session.execute.call_count, 2)
        self.assertGreaterEqual(mock_db.session.commit.call_count, 3)

    def test_catalogue_refresh_updates_airing_status(self):
        anime = anime_record(status=None)
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = refresh_catalogue(
                anime_ids=[1],
                fetch_anime=lambda _mal_id: {
                    "data": {
                        "mal_id": 1,
                        "status": "Finished Airing",
                        "genres": [],
                    }
                },
            )

        self.assertEqual(result.updated, 1)
        self.assertEqual(anime.status, "FINISHED_AIRING")

    def test_health_metrics_flag_a_low_success_run(self):
        result = CatalogueRefreshResult(selected=1000, updated=43, temporary_errors=957)
        self.assertEqual(result.skipped, 957)
        self.assertAlmostEqual(result.success_rate, 0.043)

    def test_scheduled_sync_runs_every_phase_and_reports_coverage(self):
        current = CurrentSeasonSyncResult(removed_hentai=1)
        bulk = BulkSeasonSyncResult(removed_hentai=2)
        supplemental = SupplementalCatalogueSyncResult(
            scans={"ova": BulkSeasonSyncResult(removed_hentai=3)}
        )
        backfill = SeasonBackfillResult(removed_hentai=4)
        catalogue = CatalogueRefreshResult(removed_hentai=5)
        manga_catalogue = MangaCatalogueSyncResult(
            scans={"manga": MangaTypeSyncResult(removed_adult=2)}
        )
        manga_refresh = MangaRefreshResult(removed_adult=3)
        coverage = SeasonCoverage(total_tv=100, classified_tv=75)
        with ExitStack() as stack:
            stack.enter_context(
                patch("backend.jobs.jikan_etl.remove_hentai_anime", return_value=6)
            )
            stack.enter_context(
                patch("backend.jobs.jikan_etl.remove_adult_manga", return_value=7)
            )
            stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.sync_current_season",
                    return_value=current,
                )
            )
            bulk_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.sync_bulk_anime_seasons",
                    return_value=bulk,
                )
            )
            supplemental_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.sync_supplemental_anime_types",
                    return_value=supplemental,
                )
            )
            backfill_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.backfill_missing_seasons",
                    return_value=backfill,
                )
            )
            catalogue_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.refresh_catalogue",
                    return_value=catalogue,
                )
            )
            manga_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.sync_manga_catalogue",
                    return_value=manga_catalogue,
                )
            )
            manga_refresh_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.refresh_manga_catalogue",
                    return_value=manga_refresh,
                )
            )
            facet_sync = stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.refresh_catalogue_facets",
                    return_value=123,
                )
            )
            stack.enter_context(
                patch(
                    "backend.jobs.jikan_etl.get_season_coverage",
                    return_value=coverage,
                )
            )
            for report_name in (
                "_report_current_season",
                "_report_bulk_seasons",
                "_report_supplemental_catalogue",
                "_report_season_backfill",
                "_report_catalogue",
                "report_manga_catalogue",
                "report_manga_cleanup",
                "report_manga_refresh",
                "_report_hentai_cleanup",
                "_report_catalogue_facets",
                "_report_season_coverage",
            ):
                stack.enter_context(
                    patch(f"backend.jobs.jikan_etl.{report_name}")
                )
            result = run_scheduled_sync(limit=7, batch_size=2, page_limit=3)

        bulk_sync.assert_called_once_with(max_pages=3)
        supplemental_sync.assert_called_once_with(max_pages=3)
        backfill_sync.assert_called_once_with(limit=7, batch_size=2)
        catalogue_sync.assert_called_once_with(limit=7, batch_size=2)
        manga_sync.assert_called_once_with(max_pages=3)
        manga_refresh_sync.assert_called_once_with(limit=7, batch_size=2)
        facet_sync.assert_called_once_with()
        self.assertEqual(result.supplemental_catalogue, supplemental)
        self.assertEqual(result.manga_catalogue, manga_catalogue)
        self.assertEqual(result.manga_refresh, manga_refresh)
        self.assertEqual(result.removed_adult_manga, 12)
        self.assertEqual(result.removed_hentai, 21)
        self.assertEqual(result.coverage, coverage)
        self.assertEqual(coverage.rate, 0.75)

    def test_scheduled_sync_rejects_invalid_limits_before_running(self):
        with (
            patch("backend.jobs.jikan_etl.sync_current_season") as current_sync,
            self.assertRaises(ValueError),
        ):
            run_scheduled_sync(limit=0)
        current_sync.assert_not_called()

    def test_season_sync_reuses_and_forces_listing_data(self):
        anime = SimpleNamespace(mal_id=1)
        seasonal_data = {
            "mal_id": 1,
            "title": "Example",
            "type": "TV",
            "status": "Currently Airing",
        }
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
        mapped_data = update_anime.call_args.args[1]
        self.assertEqual(mapped_data["season"], "summer")
        self.assertEqual(mapped_data["year"], 2026)
        self.assertEqual(mapped_data["status"], "Currently Airing")

    def test_season_sync_deletes_existing_hentai_records(self):
        anime = SimpleNamespace(mal_id=1)
        seasonal_data = {
            "mal_id": 1,
            "title": "Adult example",
            "type": "OVA",
            "rating": "Rx - Hentai",
        }
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            saved, skipped = sync_season(
                fetch_season=lambda _year, _season: [seasonal_data],
            )

        self.assertEqual((saved, skipped), (0, 1))
        mock_db.session.delete.assert_called_once_with(anime)

    def test_season_backfill_selects_only_pending_tv_rows(self):
        anime = SimpleNamespace(
            animeID=1,
            mal_id=101,
            season=None,
            last_season_attempt=None,
        )
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = backfill_missing_seasons(
                limit=1,
                fetch_anime=lambda _mal_id: {"data": []},
            )
            statement = mock_db.session.scalars.call_args_list[0].args[0]

        sql = str(statement).lower()
        self.assertIn("anime.season is null", sql)
        self.assertIn("upper(anime.type)", sql)
        self.assertIn("anime.last_season_attempt", sql)
        self.assertEqual(result.selected, 1)
        self.assertEqual(result.invalid_payloads, 1)
        self.assertIsNotNone(anime.last_season_attempt)

    def test_season_backfill_assigns_season_from_anime_detail(self):
        anime = SimpleNamespace(
            animeID=1,
            mal_id=101,
            season=None,
            last_season_attempt=None,
        )

        def update_anime(record, data, _genres):
            record.season = data["season"]

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._update_anime", side_effect=update_anime),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = backfill_missing_seasons(
                limit=1,
                fetch_anime=lambda _mal_id: {"data": {"season": "fall"}},
            )

        self.assertEqual(result.updated, 1)
        self.assertEqual(result.seasons_assigned, 1)
        self.assertEqual(result.still_missing, 0)
        self.assertEqual(anime.season, "fall")

    def test_season_backfill_marks_temporary_failures_and_advances_queue(self):
        records = [
            SimpleNamespace(
                animeID=index,
                mal_id=index,
                season=None,
                last_season_attempt=None,
            )
            for index in range(1, 3)
        ]

        def temporary_failure(_mal_id):
            raise JikanTemporaryError("Jikan is unavailable")

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [records, []]
            result = backfill_missing_seasons(
                limit=2,
                batch_size=1,
                fetch_anime=temporary_failure,
            )

        self.assertEqual(result.temporary_errors, 2)
        self.assertTrue(all(record.last_season_attempt for record in records))
        self.assertGreaterEqual(mock_db.session.commit.call_count, 3)

    def test_season_backfill_deletes_anime_reclassified_as_hentai(self):
        anime = SimpleNamespace(
            animeID=1,
            mal_id=101,
            season=None,
            last_season_attempt=None,
        )
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = backfill_missing_seasons(
                limit=1,
                fetch_anime=lambda _mal_id: {
                    "data": {"rating": "Rx - Hentai"}
                },
            )

        self.assertEqual(result.removed_hentai, 1)
        self.assertEqual(result.updated, 0)
        mock_db.session.delete.assert_called_once_with(anime)

    def test_current_season_resumes_failed_page(self):
        page_one = JikanSeasonPage(
            entries=[{"mal_id": 1, "type": "TV"}],
            page=1,
            has_next_page=True,
        )

        def first_run_fetch(_year, _season, *, page):
            if page == 1:
                return page_one
            raise JikanTemporaryError("page two failed")

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=1),
            patch("backend.jobs.jikan_etl._record_page_error") as record_error,
            patch(
                "backend.jobs.jikan_etl._apply_season_page",
                return_value=SeasonPageApplyResult(saved=1, seasons_assigned=1),
            ) as apply_page,
        ):
            first = sync_current_season(
                fetch_page=first_run_fetch,
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertEqual(first.pages_completed, 1)
        self.assertEqual(first.pages_failed, 1)
        self.assertEqual(first.next_page, 2)
        self.assertFalse(first.complete)
        apply_page.assert_called_once()
        self.assertEqual(record_error.call_args.args[1], 2)

        final_page = JikanSeasonPage(entries=[], page=2, has_next_page=False)
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=2),
            patch(
                "backend.jobs.jikan_etl._apply_season_page",
                return_value=SeasonPageApplyResult(),
            ) as resumed_apply,
        ):
            resumed = sync_current_season(
                fetch_page=lambda _year, _season, *, page: final_page,
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertTrue(resumed.complete)
        self.assertEqual(resumed.next_page, 1)
        self.assertEqual(resumed_apply.call_args.args[0].page, 2)

    def test_current_season_can_finish_six_pages_in_one_run(self):
        def fetch_page(_year, _season, *, page):
            return JikanSeasonPage(
                entries=[],
                page=page,
                has_next_page=page < 6,
            )

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=1),
            patch(
                "backend.jobs.jikan_etl._apply_season_page",
                return_value=SeasonPageApplyResult(),
            ) as apply_page,
        ):
            result = sync_current_season(
                fetch_page=fetch_page,
                now=datetime(2026, 7, 22, tzinfo=timezone.utc),
            )

        self.assertTrue(result.complete)
        self.assertEqual(result.pages_completed, 6)
        self.assertEqual(result.next_page, 1)
        self.assertEqual(apply_page.call_count, 6)

    def test_bulk_season_sync_commits_multiple_catalogue_pages(self):
        requested_pages = []

        def fetch_page(*, page):
            requested_pages.append(page)
            return JikanAnimePage(
                entries=[{"mal_id": page, "type": "TV", "season": "summer"}],
                page=page,
                has_next_page=page < 2,
                last_visible_page=2,
            )

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=1),
            patch(
                "backend.jobs.jikan_etl._apply_season_page",
                return_value=SeasonPageApplyResult(saved=1, seasons_assigned=1),
            ) as apply_page,
        ):
            result = sync_bulk_anime_seasons(fetch_page=fetch_page)

        self.assertEqual(requested_pages, [1, 2])
        self.assertEqual(result.pages_attempted, 2)
        self.assertEqual(result.pages_completed, 2)
        self.assertEqual(result.updated, 2)
        self.assertEqual(result.seasons_assigned, 2)
        self.assertTrue(result.complete)
        self.assertEqual(result.next_page, 1)
        self.assertEqual(apply_page.call_count, 2)

    def test_bulk_season_sync_preserves_failed_page_and_stops_during_outage(self):
        def fetch_page(*, page):
            raise JikanTemporaryError(f"page {page} unavailable")

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=4),
            patch("backend.jobs.jikan_etl._record_page_error") as record_error,
        ):
            result = sync_bulk_anime_seasons(
                max_pages=10,
                max_consecutive_failures=2,
                fetch_page=fetch_page,
            )

        self.assertEqual(result.pages_attempted, 2)
        self.assertEqual(result.pages_failed, 2)
        self.assertEqual(result.next_page, 4)
        self.assertEqual(
            [call.args[1] for call in record_error.call_args_list],
            [4, 4],
        )

    def test_bulk_page_repairs_a_stale_local_type_from_provider_tv_data(self):
        anime = SimpleNamespace(
            mal_id=1,
            type="Unknown",
            season=None,
            status=None,
        )
        state = SimpleNamespace(
            next_page=1,
            last_attempt_at=None,
            last_error=None,
            last_completed_at=None,
        )

        def update_anime(record, data, _genres):
            record.type = data["type"]
            record.season = data["season"]
            record.status = _anime_status(data.get("status"))

        page = JikanAnimePage(
            entries=[
                {
                    "mal_id": 1,
                    "type": "TV",
                    "season": "winter",
                    "status": "Currently Airing",
                }
            ],
            page=1,
            has_next_page=True,
        )
        with (
            patch("backend.jobs.jikan_etl._update_anime", side_effect=update_anime),
            patch("backend.jobs.jikan_etl._sync_state", return_value=state),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = _apply_season_page(
                page,
                state_key="test",
                year=None,
                season=None,
                discover_missing=False,
                tv_only=True,
            )

        self.assertEqual(result.saved, 1)
        self.assertEqual(result.seasons_assigned, 1)
        self.assertEqual(anime.type, "TV")
        self.assertEqual(anime.season, "winter")
        self.assertEqual(anime.status, "CURRENTLY_AIRING")

    def test_type_filtered_page_uses_requested_type_when_payload_omits_it(self):
        anime = SimpleNamespace(mal_id=1, season=None)
        state = SimpleNamespace(
            next_page=1,
            last_attempt_at=None,
            last_error=None,
            last_completed_at=None,
        )

        def update_anime(record, data, _genres):
            record.type = data["type"]

        page = JikanAnimePage(
            entries=[{"mal_id": 1, "title": "OVA example"}],
            page=1,
            has_next_page=False,
        )
        with (
            patch("backend.jobs.jikan_etl._new_anime", return_value=anime),
            patch("backend.jobs.jikan_etl._update_anime", side_effect=update_anime),
            patch("backend.jobs.jikan_etl._sync_state", return_value=state),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[], []]
            result = _apply_season_page(
                page,
                state_key="test:ova",
                year=None,
                season=None,
                discover_missing=True,
                tv_only=False,
                allowed_types=frozenset({"OVA"}),
                default_type="OVA",
            )

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.saved, 1)
        self.assertEqual(anime.type, "OVA")

    def test_type_filtered_page_removes_existing_hentai_record(self):
        anime = SimpleNamespace(mal_id=1)
        state = SimpleNamespace(
            next_page=1,
            last_attempt_at=None,
            last_error=None,
            last_completed_at=None,
        )
        page = JikanAnimePage(
            entries=[
                {
                    "mal_id": 1,
                    "type": "ONA",
                    "title": "Conflicting safe duplicate",
                },
                {
                    "mal_id": 1,
                    "type": "ONA",
                    "rating": "Rx - Hentai",
                }
            ],
            page=1,
            has_next_page=False,
        )
        with (
            patch("backend.jobs.jikan_etl._sync_state", return_value=state),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.side_effect = [[anime], []]
            result = _apply_season_page(
                page,
                state_key="test:ona",
                year=None,
                season=None,
                discover_missing=True,
                tv_only=False,
                allowed_types=frozenset({"ONA"}),
                default_type="ONA",
            )

        self.assertEqual(result.removed_hentai, 1)
        self.assertEqual(result.saved, 0)
        mock_db.session.delete.assert_called_once_with(anime)

    def test_supplemental_sync_uses_independent_type_cursors(self):
        scan_results = [
            BulkSeasonSyncResult(inserted=index)
            for index in range(1, len(SUPPLEMENTAL_PROVIDER_TYPES) + 1)
        ]
        with patch(
            "backend.jobs.jikan_etl._sync_bulk_anime_type",
            side_effect=scan_results,
        ) as sync_type:
            result = sync_supplemental_anime_types(max_pages=7)

        self.assertEqual(sync_type.call_count, len(SUPPLEMENTAL_PROVIDER_TYPES))
        for anime_type, sync_call in zip(
            SUPPLEMENTAL_PROVIDER_TYPES,
            sync_type.call_args_list,
            strict=True,
        ):
            self.assertEqual(sync_call.kwargs["anime_type"], anime_type)
            self.assertEqual(
                sync_call.kwargs["state_key"],
                SUPPLEMENTAL_STATE_KEYS[anime_type],
            )
            self.assertTrue(sync_call.kwargs["discover_missing"])
            self.assertEqual(sync_call.kwargs["max_pages"], 7)
            self.assertEqual(sync_call.kwargs["max_consecutive_failures"], 3)
        self.assertEqual(result.inserted, sum(range(1, 5)))

    def test_cleanup_deletes_matching_adult_anime_but_keeps_shared_genres(self):
        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl.db") as mock_db,
        ):
            mock_db.session.scalars.return_value = [10, 20]
            removed = remove_hentai_anime()

        self.assertEqual(removed, 2)
        # The shared Genre row is retained because Manga/Manhwa may still
        # reference the same normalized value; only links and anime are deleted.
        self.assertEqual(mock_db.session.execute.call_count, 2)
        cleanup_sql = str(mock_db.session.scalars.call_args.args[0]).lower()
        self.assertIn("anime_genre", cleanup_sql)
        self.assertIn("unnest(anime.genres)", cleanup_sql)
        self.assertIn("unnest(anime.genres_detailed)", cleanup_sql)
        mock_db.session.commit.assert_called_once()

    def test_bulk_rate_limit_stops_without_advancing_cursor(self):
        def rate_limited(*, page):
            raise HTTPError(
                f"https://example.test/anime?page={page}",
                429,
                "rate limited",
                Message(),
                None,
            )

        with (
            patch("backend.jobs.jikan_etl._ensure_schema"),
            patch("backend.jobs.jikan_etl._next_page", return_value=12),
            patch("backend.jobs.jikan_etl._record_page_error") as record_error,
        ):
            result = sync_bulk_anime_seasons(fetch_page=rate_limited)

        self.assertEqual(result.pages_attempted, 1)
        self.assertEqual(result.pages_failed, 1)
        self.assertEqual(result.next_page, 12)
        self.assertEqual(record_error.call_args.args[1], 12)

    def test_bulk_season_sync_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            sync_bulk_anime_seasons(max_pages=0)
        with self.assertRaises(ValueError):
            sync_bulk_anime_seasons(max_consecutive_failures=0)

    def test_backfill_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            backfill_missing_seasons(limit=0)
        with self.assertRaises(ValueError):
            backfill_missing_seasons(batch_size=0)


if __name__ == "__main__":
    unittest.main()

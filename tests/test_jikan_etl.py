import unittest
from datetime import datetime, timezone
from email.message import Message
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from backend.jobs.jikan_etl import (
    BulkSeasonSyncResult,
    CatalogueRefreshResult,
    CurrentSeasonSyncResult,
    SeasonPageApplyResult,
    SeasonBackfillResult,
    SeasonCoverage,
    _apply_season_page,
    _detailed_genres,
    _current_season_identity,
    _fetch_anime_data,
    _names,
    _prepared_season_entry,
    _season,
    _season_from_air_date,
    _update_anime,
    _valid_score,
    backfill_missing_seasons,
    refresh_catalogue,
    run_scheduled_sync,
    sync_bulk_anime_seasons,
    sync_current_season,
    sync_season,
)
from backend.models import Anime
from backend.services.jikan_client import (
    JikanAnimePage,
    JikanSeasonPage,
    JikanTemporaryError,
)


def anime_record(*, anime_type="TV", season="summer"):
    return Anime(
        animeID=1,
        mal_id=1,
        title="Example",
        alternative_title=None,
        type=anime_type,
        season=season,
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

    def test_updates_anime_season_from_jikan(self):
        anime = anime_record()
        _update_anime(anime, {"season": "Fall", "genres": []}, {})
        self.assertEqual(anime.season, "fall")

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

    def test_health_metrics_flag_a_low_success_run(self):
        result = CatalogueRefreshResult(selected=1000, updated=43, temporary_errors=957)
        self.assertEqual(result.skipped, 957)
        self.assertAlmostEqual(result.success_rate, 0.043)

    def test_scheduled_sync_runs_every_phase_and_reports_coverage(self):
        current = CurrentSeasonSyncResult()
        bulk = BulkSeasonSyncResult()
        backfill = SeasonBackfillResult()
        catalogue = CatalogueRefreshResult()
        coverage = SeasonCoverage(total_tv=100, classified_tv=75)
        with (
            patch("backend.jobs.jikan_etl.sync_current_season", return_value=current),
            patch(
                "backend.jobs.jikan_etl.sync_bulk_anime_seasons", return_value=bulk
            ) as bulk_sync,
            patch(
                "backend.jobs.jikan_etl.backfill_missing_seasons", return_value=backfill
            ) as backfill_sync,
            patch(
                "backend.jobs.jikan_etl.refresh_catalogue", return_value=catalogue
            ) as catalogue_sync,
            patch("backend.jobs.jikan_etl.get_season_coverage", return_value=coverage),
            patch("backend.jobs.jikan_etl._report_current_season"),
            patch("backend.jobs.jikan_etl._report_bulk_seasons"),
            patch("backend.jobs.jikan_etl._report_season_backfill"),
            patch("backend.jobs.jikan_etl._report_catalogue"),
            patch("backend.jobs.jikan_etl._report_season_coverage"),
        ):
            result = run_scheduled_sync(limit=7, batch_size=2, page_limit=3)

        bulk_sync.assert_called_once_with(max_pages=3)
        backfill_sync.assert_called_once_with(limit=7, batch_size=2)
        catalogue_sync.assert_called_once_with(limit=7, batch_size=2)
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
        seasonal_data = {"mal_id": 1, "title": "Example", "type": "TV"}
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
        anime = SimpleNamespace(mal_id=1, type="Unknown", season=None)
        state = SimpleNamespace(
            next_page=1,
            last_attempt_at=None,
            last_error=None,
            last_completed_at=None,
        )

        def update_anime(record, data, _genres):
            record.type = data["type"]
            record.season = data["season"]

        page = JikanAnimePage(
            entries=[{"mal_id": 1, "type": "TV", "season": "winter"}],
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

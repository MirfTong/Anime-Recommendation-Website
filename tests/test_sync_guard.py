import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.jobs.sync_guard import (
    _successful_scheduled_etl_runs,
    main,
    should_run_scheduled_sync,
)


class SyncGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)

    def test_first_scheduled_run_is_allowed(self):
        should_run, _reason = should_run_scheduled_sync(
            [], now=self.now, minimum_hours=72
        )

        self.assertTrue(should_run)

    def test_no_previous_real_etl_is_allowed(self):
        guard_only_run = {
            "id": 100,
            "run_started_at": (self.now - timedelta(hours=24)).isoformat(),
        }
        skipped_job = {
            "steps": [
                {
                    "name": "Sync Anime, Manga, and Manhwa",
                    "conclusion": "skipped",
                    "completed_at": None,
                }
            ]
        }

        with (
            patch(
                "backend.jobs.sync_guard._successful_scheduled_runs",
                return_value=([guard_only_run], 1),
            ),
            patch(
                "backend.jobs.sync_guard._jobs_for_run", return_value=[skipped_job]
            ),
        ):
            verified_runs = _successful_scheduled_etl_runs(
                repository="owner/repo", workflow="jikan-sync.yml", token="token"
            )

        should_run, _reason = should_run_scheduled_sync(
            verified_runs, now=self.now, minimum_hours=72
        )
        self.assertTrue(should_run)

    def test_recent_success_is_skipped(self):
        should_run, reason = should_run_scheduled_sync(
            [{"run_started_at": (self.now - timedelta(hours=71)).isoformat()}],
            now=self.now,
            minimum_hours=72,
        )

        self.assertFalse(should_run)
        self.assertIn("next run is allowed", reason)

    def test_success_at_exact_interval_is_allowed(self):
        should_run, _reason = should_run_scheduled_sync(
            [{"run_started_at": (self.now - timedelta(hours=72)).isoformat()}],
            now=self.now,
            minimum_hours=72,
        )

        self.assertTrue(should_run)

    def test_manual_dispatch_bypasses_github_api_lookup(self):
        with (
            patch.dict(
                "os.environ",
                {"GITHUB_EVENT_NAME": "workflow_dispatch"},
                clear=True,
            ),
            patch("sys.argv", ["sync_guard", "--workflow", "jikan-sync.yml"]),
            patch("backend.jobs.sync_guard._successful_scheduled_runs") as lookup,
            patch("backend.jobs.sync_guard._write_output") as output,
            patch("backend.jobs.sync_guard._write_summary"),
        ):
            main()

        lookup.assert_not_called()
        output.assert_called_once_with("should_run", "true")

    def test_successful_guard_only_runs_do_not_delay_the_next_etl(self):
        runs = [
            {
                "id": run_id,
                "run_started_at": (self.now - timedelta(hours=hours_ago)).isoformat(),
            }
            for run_id, hours_ago in ((300, 24), (200, 48), (100, 73))
        ]
        skipped_step = {
            "steps": [
                {
                    "name": "Sync Anime, Manga, and Manhwa",
                    "conclusion": "skipped",
                    "completed_at": None,
                }
            ]
        }
        successful_step = {
            "steps": [
                {
                    "name": "Sync Anime, Manga, and Manhwa",
                    "conclusion": "success",
                    "completed_at": (self.now - timedelta(hours=73)).isoformat(),
                }
            ]
        }

        with (
            patch(
                "backend.jobs.sync_guard._successful_scheduled_runs",
                return_value=(runs, len(runs)),
            ),
            patch(
                "backend.jobs.sync_guard._jobs_for_run",
                side_effect=[[skipped_step], [skipped_step], [successful_step]],
            ),
        ):
            verified_runs = _successful_scheduled_etl_runs(
                repository="owner/repo", workflow="jikan-sync.yml", token="token"
            )

        should_run, _reason = should_run_scheduled_sync(
            verified_runs, now=self.now, minimum_hours=72
        )
        self.assertTrue(should_run)
        self.assertEqual([run["id"] for run in verified_runs], [100])

    def test_api_failure_fails_closed_without_enabling_database_write(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "GITHUB_EVENT_NAME": "schedule",
                    "GITHUB_REPOSITORY": "owner/repo",
                    "GITHUB_TOKEN": "token",
                },
                clear=True,
            ),
            patch("sys.argv", ["sync_guard", "--workflow", "jikan-sync.yml"]),
            patch(
                "backend.jobs.sync_guard._successful_scheduled_etl_runs",
                side_effect=OSError("API unavailable"),
            ),
            patch("backend.jobs.sync_guard._write_output") as output,
            patch("backend.jobs.sync_guard._write_summary") as summary,
        ):
            with self.assertRaises(SystemExit):
                main()

        output.assert_called_once_with("should_run", "false")
        summary.assert_called_once()
        self.assertNotIn(
            ("should_run", "true"),
            [call.args for call in output.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()

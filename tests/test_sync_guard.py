import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend.jobs.sync_guard import main, should_run_scheduled_sync


class SyncGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 14, 12, tzinfo=timezone.utc)

    def test_first_scheduled_run_is_allowed(self):
        should_run, _reason = should_run_scheduled_sync(
            [], now=self.now, minimum_hours=72
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


if __name__ == "__main__":
    unittest.main()

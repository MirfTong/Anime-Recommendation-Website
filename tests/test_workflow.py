import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "jikan-sync.yml"
)


class JikanWorkflowTests(unittest.TestCase):
    def test_sync_runs_every_three_hours_without_self_dispatch(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn('cron: "0 */3 * * *"', workflow)
        self.assertNotIn("gh workflow run", workflow)
        self.assertNotIn("actions: write", workflow)

    def test_sync_includes_bulk_and_detail_season_paths(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("--bulk-seasons --page-limit 40", workflow)
        self.assertIn("--backfill-seasons --limit 1000", workflow)


if __name__ == "__main__":
    unittest.main()

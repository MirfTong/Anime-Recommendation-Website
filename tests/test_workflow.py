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

    def test_sync_runs_all_phases_in_one_rate_limited_process(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")

        command = (
            "python -m backend.jobs.jikan_etl "
            "--scheduled-sync --page-limit 40 --limit 1000 "
            "--streaming-limit 2000"
        )
        self.assertIn(command, workflow)
        self.assertEqual(workflow.count("python -m backend.jobs.jikan_etl"), 1)
        self.assertIn("Sync Anime, Manga, and Manhwa", workflow)
        self.assertIn("Scheduled catalogue metadata sync", workflow)


if __name__ == "__main__":
    unittest.main()

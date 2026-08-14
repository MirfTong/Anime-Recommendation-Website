import unittest

from backend.jobs.database_maintenance import DUPLICATE_CHECKS, cleanup_targets


class DatabaseMaintenanceTests(unittest.TestCase):
    def test_cleanup_is_limited_to_expired_analytics_and_orphans(self):
        targets = cleanup_targets(365)
        delete_sql = " ".join(target.delete_sql for target in targets).lower()

        self.assertIn("site_visit", delete_sql)
        self.assertIn("interval '365 days'", delete_sql)
        self.assertIn("not exists", delete_sql)
        self.assertNotIn("delete from anime ", delete_sql)
        self.assertNotIn("delete from manga ", delete_sql)

    def test_duplicate_audit_covers_catalogue_natural_keys_and_join_pairs(self):
        labels = {label for label, _statement in DUPLICATE_CHECKS}

        self.assertIn("anime.mal_id", labels)
        self.assertIn("manga.mal_id", labels)
        self.assertIn("anime_streaming_service pair", labels)
        self.assertIn("manga_author pair", labels)


if __name__ == "__main__":
    unittest.main()

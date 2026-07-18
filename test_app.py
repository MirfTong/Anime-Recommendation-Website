import unittest

from app import app


class AppTests(unittest.TestCase):
    def test_browse_omits_unrated_anime(self):
        with app.test_client() as client:
            response = client.get("/?search=Bleach")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Bleach: Sennen Kessen-hen - Kashin-tan", html)


if __name__ == "__main__":
    unittest.main()

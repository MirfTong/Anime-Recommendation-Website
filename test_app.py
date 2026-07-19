import unittest

from app import app


class AppTests(unittest.TestCase):
    def test_browse_omits_unrated_anime(self):
        with app.test_client() as client:
            response = client.get("/?search=Bleach")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Bleach: Sennen Kessen-hen - Kashin-tan", html)

    def test_min_year_filter_is_preserved_in_the_form(self):
        with app.test_client() as client:
            response = client.get("/?min_year=2020")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="min_year" value="2020"', html)


if __name__ == "__main__":
    unittest.main()

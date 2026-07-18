import unittest

from import_anime import parse_mal_id


class ImportAnimeTests(unittest.TestCase):
    def test_extracts_mal_id_from_anime_url(self):
        self.assertEqual(
            parse_mal_id("https://myanimelist.net/anime/269/Bleach"), 269
        )

    def test_rejects_a_url_without_an_anime_id(self):
        with self.assertRaises(ValueError):
            parse_mal_id("https://myanimelist.net/topanime.php")


if __name__ == "__main__":
    unittest.main()

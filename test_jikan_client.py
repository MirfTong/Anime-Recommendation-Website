import io
import unittest
from email.message import Message
from urllib.error import HTTPError

from jikan_client import JikanClient


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class JikanClientTests(unittest.TestCase):
    def test_fetches_full_anime_payload(self):
        seen_urls = []

        def opener(request, *, timeout):
            seen_urls.append(request.full_url)
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(opener=opener)

        self.assertEqual(client.get_anime_full(1), {"data": {"mal_id": 1}})
        self.assertEqual(seen_urls, ["https://api.jikan.moe/v4/anime/1/full"])

    def test_retries_429_using_retry_after(self):
        clock = FakeClock()
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                headers = Message()
                headers["Retry-After"] = "2"
                raise HTTPError(request.full_url, 429, "Too Many Requests", headers, None)
            return Response(b'{"data": {}}')

        client = JikanClient(opener=opener, clock=clock, sleeper=clock.sleep)

        self.assertEqual(client.get_anime_full(1), {"data": {}})
        self.assertEqual(calls, 2)
        self.assertIn(2.0, clock.sleeps)

    def test_throttles_to_three_requests_per_second(self):
        clock = FakeClock()

        def opener(request, *, timeout):
            return Response(b'{"data": {}}')

        client = JikanClient(opener=opener, clock=clock, sleeper=clock.sleep)
        for _ in range(3):
            client.get_anime_full(1)

        self.assertEqual(clock.sleeps, [1 / 3, 1 / 3])

    def test_gets_all_season_pages(self):
        requested_urls = []
        responses = iter(
            [
                Response(b'{"data": [{"mal_id": 1}], "pagination": {"has_next_page": true}}'),
                Response(b'{"data": [{"mal_id": 2}], "pagination": {"has_next_page": false}}'),
            ]
        )

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            return next(responses)

        client = JikanClient(opener=opener)

        self.assertEqual(client.get_season_anime(2026, "summer"), [{"mal_id": 1}, {"mal_id": 2}])
        self.assertEqual(
            requested_urls,
            [
                "https://api.jikan.moe/v4/seasons/2026/summer?page=1",
                "https://api.jikan.moe/v4/seasons/2026/summer?page=2",
            ],
        )

    def test_rejects_invalid_mal_id(self):
        client = JikanClient(opener=lambda *args, **kwargs: None)

        with self.assertRaises(ValueError):
            client.get_anime_full(0)


if __name__ == "__main__":
    unittest.main()

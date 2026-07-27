import io
import unittest
from email.message import Message
from urllib.error import HTTPError

from backend.services.jikan_client import (
    JikanAnimePage,
    JikanClient,
    JikanSeasonPage,
    JikanTemporaryError,
    PRIMARY_429_COOLDOWN_SECONDS,
)


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


def http_error(url: str, status: int) -> HTTPError:
    return HTTPError(url, status, "request failed", Message(), None)


class JikanClientTests(unittest.TestCase):
    def test_fetches_basic_anime_without_calling_full_endpoint(self):
        seen_urls = []

        def opener(request, *, timeout):
            seen_urls.append(request.full_url)
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(opener=opener, fallback_base_url="")

        self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
        self.assertEqual(seen_urls, ["https://api.tenrai.org/v1/anime/1"])

    def test_fetches_full_anime_payload(self):
        seen_urls = []

        def opener(request, *, timeout):
            seen_urls.append(request.full_url)
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(opener=opener)

        self.assertEqual(client.get_anime_full(1), {"data": {"mal_id": 1}})
        self.assertEqual(seen_urls, ["https://api.tenrai.org/v1/anime/1/full"])

    def test_supports_configurable_primary_and_fallback_providers(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.startswith("https://primary.example"):
                raise http_error(request.full_url, 504)
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(
            opener=opener,
            transient_retry_budget=0,
            base_url="https://primary.example/v1/",
            fallback_base_url="https://fallback.example/v4/",
        )

        self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
        self.assertEqual(
            requested_urls,
            [
                "https://primary.example/v1/anime/1",
                "https://fallback.example/v4/anime/1",
            ],
        )

    def test_retries_429_using_retry_after(self):
        clock = FakeClock()
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                error = http_error(request.full_url, 429)
                error.headers["Retry-After"] = "2"
                raise error
            return Response(b'{"data": {}}')

        client = JikanClient(opener=opener, clock=clock, sleeper=clock.sleep)

        self.assertEqual(client.get_anime_full(1), {"data": {}})
        self.assertEqual(calls, 2)
        self.assertIn(2.0, clock.sleeps)

    def test_exhausted_primary_429_uses_fallback_and_cools_primary(self):
        clock = FakeClock()
        primary_calls = 0
        fallback_calls = 0

        def opener(request, *, timeout):
            nonlocal primary_calls, fallback_calls
            if request.full_url.startswith("https://primary.example"):
                primary_calls += 1
                error = http_error(request.full_url, 429)
                error.headers["Retry-After"] = "0"
                raise error
            fallback_calls += 1
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(
            opener=opener,
            clock=clock,
            sleeper=clock.sleep,
            base_url="https://primary.example/v1",
            fallback_base_url="https://fallback.example/v4",
        )

        self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
        self.assertEqual(primary_calls, 5)
        self.assertEqual(fallback_calls, 1)

        self.assertEqual(client.get_anime(2), {"data": {"mal_id": 1}})
        self.assertEqual(primary_calls, 5)
        self.assertEqual(fallback_calls, 2)

        clock.sleep(PRIMARY_429_COOLDOWN_SECONDS + 1)
        self.assertEqual(client.get_anime(3), {"data": {"mal_id": 1}})
        self.assertEqual(primary_calls, 10)
        self.assertEqual(fallback_calls, 3)

    def test_retries_one_gateway_error_then_succeeds(self):
        clock = FakeClock()
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise http_error(request.full_url, 504)
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(opener=opener, clock=clock, sleeper=clock.sleep)

        self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
        self.assertEqual(calls, 2)
        self.assertIn(1.0, clock.sleeps)

    def test_transient_retry_budget_caps_outage_requests(self):
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            raise http_error(request.full_url, 504)

        client = JikanClient(
            opener=opener,
            transient_retry_budget=0,
            fallback_base_url="",
        )

        with self.assertRaises(HTTPError) as raised:
            client.get_anime(1)

        self.assertEqual(raised.exception.code, 504)
        self.assertEqual(calls, 1)

    def test_does_not_retry_not_found(self):
        calls = 0

        def opener(request, *, timeout):
            nonlocal calls
            calls += 1
            raise http_error(request.full_url, 404)

        client = JikanClient(opener=opener, fallback_base_url="")

        with self.assertRaises(HTTPError) as raised:
            client.get_anime(999999)

        self.assertEqual(raised.exception.code, 404)
        self.assertEqual(calls, 1)

    def test_falls_back_to_basic_endpoint_when_full_endpoint_times_out(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.endswith("/full"):
                raise TimeoutError("Jikan full endpoint timed out")
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(opener=opener, fallback_base_url="")

        self.assertEqual(client.get_anime_full(1), {"data": {"mal_id": 1}})
        self.assertEqual(
            requested_urls,
            [
                "https://api.tenrai.org/v1/anime/1/full",
                "https://api.tenrai.org/v1/anime/1",
            ],
        )

    def test_throttles_to_three_requests_per_second(self):
        clock = FakeClock()

        def opener(request, *, timeout):
            return Response(b'{"data": {}}')

        client = JikanClient(opener=opener, clock=clock, sleeper=clock.sleep)
        for _ in range(3):
            client.get_anime_full(1)

        self.assertEqual(clock.sleeps, [1 / 3, 1 / 3])

    def test_returns_one_season_page_with_cursor_metadata(self):
        def opener(request, *, timeout):
            return Response(
                b'{"data": [{"mal_id": 1}], "pagination": {"has_next_page": true}}'
            )

        client = JikanClient(opener=opener)

        self.assertEqual(
            client.get_season_page(2026, "summer"),
            JikanSeasonPage(entries=[{"mal_id": 1}], page=1, has_next_page=True),
        )

    def test_season_pages_are_pinned_to_the_primary_provider(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.startswith("https://primary.example"):
                raise http_error(request.full_url, 504)
            return Response(b'{"data": [], "pagination": {"has_next_page": false}}')

        client = JikanClient(
            opener=opener,
            transient_retry_budget=0,
            base_url="https://primary.example/v1",
            fallback_base_url="https://fallback.example/v4",
        )

        with self.assertRaises(HTTPError) as raised:
            client.get_season_page(2026, "summer", page=2)

        self.assertEqual(raised.exception.code, 504)
        self.assertEqual(
            requested_urls,
            ["https://primary.example/v1/seasons/2026/summer?page=2"],
        )

    def test_season_page_429_never_uses_the_fallback_provider(self):
        clock = FakeClock()
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.startswith("https://primary.example"):
                error = http_error(request.full_url, 429)
                error.headers["Retry-After"] = "0"
                raise error
            return Response(b'{"data": {"mal_id": 1}}')

        client = JikanClient(
            opener=opener,
            clock=clock,
            sleeper=clock.sleep,
            base_url="https://primary.example/v1",
            fallback_base_url="https://fallback.example/v4",
        )

        with self.assertRaises(HTTPError) as raised:
            client.get_season_page(2026, "summer")

        self.assertEqual(raised.exception.code, 429)
        self.assertEqual(len(requested_urls), 5)
        self.assertTrue(
            all(url.startswith("https://primary.example") for url in requested_urls)
        )

        page_attempts = len(requested_urls)
        with self.assertRaises(JikanTemporaryError):
            client.get_anime_catalogue_page()
        self.assertEqual(len(requested_urls), page_attempts)

        self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
        self.assertTrue(requested_urls[-1].startswith("https://fallback.example"))

    def test_season_page_rejects_invalid_page_envelopes(self):
        invalid_payloads = (
            b'{"data": null, "pagination": {"has_next_page": false}}',
            b'{"data": {}, "pagination": {"has_next_page": false}}',
            b'{"data": []}',
            b'{"data": [], "pagination": null}',
            b'{"data": [], "pagination": {}}',
            b'{"data": [], "pagination": {"has_next_page": 0}}',
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client = JikanClient(
                    opener=lambda request, *, timeout: Response(payload),
                    fallback_base_url="",
                )

                with self.assertRaises(JikanTemporaryError):
                    client.get_season_page(2026, "summer")

    def test_gets_all_season_pages(self):
        requested_urls = []
        responses = iter(
            [
                Response(
                    b'{"data": [{"mal_id": 1}], "pagination": {"has_next_page": true}}'
                ),
                Response(
                    b'{"data": [{"mal_id": 2}], "pagination": {"has_next_page": false}}'
                ),
            ]
        )

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            return next(responses)

        client = JikanClient(opener=opener)

        self.assertEqual(
            client.get_season_anime(2026, "summer"),
            [{"mal_id": 1}, {"mal_id": 2}],
        )
        self.assertEqual(
            requested_urls,
            [
                "https://api.tenrai.org/v1/seasons/2026/summer",
                "https://api.tenrai.org/v1/seasons/2026/summer?page=2",
            ],
        )

    def test_returns_bulk_anime_catalogue_page(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            return Response(
                b'{"data": [{"mal_id": 1}], "pagination": '
                b'{"has_next_page": true, "last_visible_page": 100}}'
            )

        client = JikanClient(opener=opener)

        self.assertEqual(
            client.get_anime_catalogue_page(page=2),
            JikanAnimePage(
                entries=[{"mal_id": 1}],
                page=2,
                has_next_page=True,
                last_visible_page=100,
            ),
        )
        self.assertEqual(
            requested_urls,
            [
                "https://api.tenrai.org/v1/anime?type=tv&limit=50&order_by=mal_id&sort=asc&page=2"
            ],
        )

    def test_bulk_catalogue_supports_supplemental_anime_types(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            return Response(
                b'{"data": [], "pagination": {"has_next_page": false}}'
            )

        client = JikanClient(opener=opener)

        client.get_anime_catalogue_page(anime_type=" OVA ", page=4)

        self.assertEqual(
            requested_urls,
            [
                "https://api.tenrai.org/v1/anime?type=ova&limit=50&order_by=mal_id&sort=asc&page=4"
            ],
        )

    def test_bulk_catalogue_rejects_unsupported_anime_types(self):
        client = JikanClient(opener=lambda *args, **kwargs: None)

        with self.assertRaises(ValueError):
            client.get_anime_catalogue_page(anime_type="movie")

    def test_bulk_catalogue_pages_are_pinned_to_the_primary_provider(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.startswith("https://primary.example"):
                raise http_error(request.full_url, 504)
            return Response(b'{"data": [], "pagination": {"has_next_page": false}}')

        client = JikanClient(
            opener=opener,
            transient_retry_budget=0,
            base_url="https://primary.example/v1",
            fallback_base_url="https://fallback.example/v4",
        )

        with self.assertRaises(HTTPError) as raised:
            client.get_anime_catalogue_page(page=3)

        self.assertEqual(raised.exception.code, 504)
        self.assertEqual(
            requested_urls,
            [
                "https://primary.example/v1/anime?type=tv&limit=50&order_by=mal_id&sort=asc&page=3"
            ],
        )

    def test_bulk_catalogue_page_rejects_invalid_page_envelopes(self):
        invalid_payloads = (
            b'{"data": null, "pagination": {"has_next_page": false}}',
            b'{"data": [], "pagination": []}',
            b'{"data": [], "pagination": {"has_next_page": "false"}}',
            b'{"data": [], "pagination": '
            b'{"has_next_page": false, "last_visible_page": "1"}}',
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                client = JikanClient(
                    opener=lambda request, *, timeout: Response(payload),
                    fallback_base_url="",
                )

                with self.assertRaises(JikanTemporaryError):
                    client.get_anime_catalogue_page()

    def test_per_anime_request_falls_back_after_malformed_success_response(self):
        for malformed_response in (b"not-json", b"[]"):
            with self.subTest(response=malformed_response):
                requested_urls = []

                def opener(request, *, timeout):
                    requested_urls.append(request.full_url)
                    if request.full_url.startswith("https://primary.example"):
                        return Response(malformed_response)
                    return Response(b'{"data": {"mal_id": 1}}')

                client = JikanClient(
                    opener=opener,
                    base_url="https://primary.example/v1",
                    fallback_base_url="https://fallback.example/v4",
                )

                self.assertEqual(client.get_anime(1), {"data": {"mal_id": 1}})
                self.assertEqual(
                    requested_urls,
                    [
                        "https://primary.example/v1/anime/1",
                        "https://fallback.example/v4/anime/1",
                    ],
                )

    def test_malformed_season_page_does_not_use_fallback_provider(self):
        requested_urls = []

        def opener(request, *, timeout):
            requested_urls.append(request.full_url)
            if request.full_url.startswith("https://primary.example"):
                return Response(b"[]")
            return Response(b'{"data": [], "pagination": {"has_next_page": false}}')

        client = JikanClient(
            opener=opener,
            base_url="https://primary.example/v1",
            fallback_base_url="https://fallback.example/v4",
        )

        with self.assertRaises(JikanTemporaryError):
            client.get_season_page(2026, "summer")

        self.assertEqual(
            requested_urls,
            ["https://primary.example/v1/seasons/2026/summer"],
        )

    def test_rejects_invalid_mal_id(self):
        client = JikanClient(opener=lambda *args, **kwargs: None)

        with self.assertRaises(ValueError):
            client.get_anime_full(0)
        with self.assertRaises(ValueError):
            client.get_anime_catalogue_page(page=0)


if __name__ == "__main__":
    unittest.main()

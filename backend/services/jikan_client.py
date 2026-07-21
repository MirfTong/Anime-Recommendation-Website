"""Small, rate-limited client for the Jikan v4 API."""

from __future__ import annotations

import json
import threading
import time
import warnings
from collections import deque
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.jikan.moe/v4"
REQUESTS_PER_SECOND = 3
REQUESTS_PER_MINUTE = 60
MAX_429_RETRIES = 4
REQUEST_TIMEOUT_SECONDS = 20
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class JikanTemporaryError(RuntimeError):
    """Jikan could not be reached after transient-request retries."""


class JikanClient:
    """Fetch Jikan resources while respecting its public request limits.

    The limiter is shared by every request made through an instance.  It spaces
    requests by at least one third of a second and prevents more than 60 calls
    in any rolling 60-second period.
    """

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._request_times: deque[float] = deque()
        self._last_request_time: float | None = None
        self._lock = threading.Lock()

    def get_anime_full(self, mal_id: int) -> dict[str, Any]:
        """Return Jikan anime data, preferring ``GET /anime/{mal_id}/full``.

        A 429 response is retried up to ``MAX_429_RETRIES`` times and honors
        the server's ``Retry-After`` header. Server failures fall back to the
        basic endpoint once, then return control to the ETL queue so a bad
        Jikan record cannot consume an entire sync run.
        """
        if isinstance(mal_id, bool) or not isinstance(mal_id, int) or mal_id <= 0:
            raise ValueError("mal_id must be a positive integer")

        try:
            # The full endpoint occasionally times out while the basic anime
            # endpoint remains available. Do not delay a catalogue sync when
            # that happens; the basic response contains the fields we store.
            return self._get(
                f"/anime/{mal_id}/full",
                retryable_status_codes=frozenset({429}),
                retry_network_errors=False,
            )
        except (HTTPError, JikanTemporaryError) as error:
            if (
                isinstance(error, HTTPError)
                and error.code not in RETRYABLE_STATUS_CODES - {429}
            ):
                raise
            return self._get(
                f"/anime/{mal_id}",
                retryable_status_codes=frozenset({429}),
                retry_network_errors=False,
            )

    def get_season_anime(
        self, year: int | None = None, season: str | None = None
    ) -> list[dict[str, Any]]:
        """Return every anime listed for the current or a specified season."""
        if (year is None) != (season is None):
            raise ValueError("year and season must be supplied together")
        if season is not None and season not in {"winter", "spring", "summer", "fall"}:
            raise ValueError("season must be winter, spring, summer, or fall")

        path = "/seasons/now" if year is None else f"/seasons/{year}/{season}"
        # Jikan's current-season endpoint serves its first page without a query
        # string; some deployments return a 504 for the equivalent ``?page=1``.
        # Keep the first request query-free, then paginate normally if needed.
        page = 1
        anime: list[dict[str, Any]] = []
        while True:
            request_path = path if page == 1 else f"{path}?page={page}"
            try:
                payload = self._get(request_path)
            except (HTTPError, JikanTemporaryError) as error:
                is_retryable = isinstance(error, JikanTemporaryError) or (
                    error.code in RETRYABLE_STATUS_CODES
                )
                if year is None and page > 1 and is_retryable:
                    warnings.warn(
                        "Jikan could not return additional current-season pages; "
                        "using the available first page.",
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    return anime
                raise
            data = payload.get("data")
            if not isinstance(data, list):
                raise ValueError("Jikan seasonal response did not contain an anime list")
            anime.extend(entry for entry in data if isinstance(entry, dict))
            if not payload.get("pagination", {}).get("has_next_page"):
                return anime
            page += 1

    def _get(
        self,
        path: str,
        *,
        retryable_status_codes: frozenset[int] = RETRYABLE_STATUS_CODES,
        retry_network_errors: bool = True,
    ) -> dict[str, Any]:
        """Fetch one Jikan JSON response, applying retries and rate limits."""
        url = f"{BASE_URL}{path}"
        for attempt in range(MAX_429_RETRIES + 1):
            self._throttle()
            request = Request(url, headers={"Accept": "application/json"})
            try:
                with self._opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in retryable_status_codes or attempt == MAX_429_RETRIES:
                    error.close()
                    raise
                delay = self._retry_delay(error, attempt)
                error.close()
                self._sleeper(delay)
            except (TimeoutError, URLError) as error:
                if not retry_network_errors or attempt == MAX_429_RETRIES:
                    raise JikanTemporaryError(f"Jikan request timed out: {path}") from error
                self._sleeper(float(2**attempt))

        raise RuntimeError("unreachable")

    def _throttle(self) -> None:
        """Block until the next request meets the per-second and per-minute caps."""
        with self._lock:
            now = self._clock()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()

            delays = [0.0]
            if self._last_request_time is not None:
                delays.append(
                    self._last_request_time + (1 / REQUESTS_PER_SECOND) - now
                )
            if len(self._request_times) >= REQUESTS_PER_MINUTE:
                delays.append(self._request_times[0] + 60 - now)

            delay = max(delays)
            if delay > 0:
                self._sleeper(delay)
                now = self._clock()
                while self._request_times and now - self._request_times[0] >= 60:
                    self._request_times.popleft()

            self._request_times.append(now)
            self._last_request_time = now

    @staticmethod
    def _retry_delay(error: HTTPError, attempt: int) -> float:
        """Use Retry-After when available, otherwise exponential backoff."""
        retry_after = error.headers.get("Retry-After") if error.headers else None
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass
        return float(2**attempt)


_default_client = JikanClient()


def get_anime_full(mal_id: int) -> dict[str, Any]:
    """Return the parsed Jikan v4 full-anime payload for a MyAnimeList ID."""
    return _default_client.get_anime_full(mal_id)


def get_season_anime(
    year: int | None = None, season: str | None = None
) -> list[dict[str, Any]]:
    """Return anime from Jikan's current or a specified season."""
    return _default_client.get_season_anime(year, season)

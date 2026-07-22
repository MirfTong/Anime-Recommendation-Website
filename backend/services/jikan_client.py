"""Small, rate-limited client for the Jikan v4 API."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = "https://api.jikan.moe/v4"
REQUESTS_PER_SECOND = 3
# Leave a little headroom beneath Jikan's approximate public 60/minute cap.
REQUESTS_PER_MINUTE = 55
MAX_429_RETRIES = 4
MAX_ANIME_TRANSIENT_RETRIES = 1
MAX_SEASON_TRANSIENT_RETRIES = 2
MAX_TRANSIENT_RETRY_BUDGET = 100
REQUEST_TIMEOUT_SECONDS = 20
SERVER_ERROR_STATUS_CODES = frozenset({500, 502, 503, 504})
USER_AGENT = "KyoQuan/1.0 (+https://github.com/MirfTong/Anime-Recommendation-Website)"


class JikanTemporaryError(RuntimeError):
    """Jikan could not be reached after bounded transient-request retries."""


@dataclass(frozen=True)
class JikanSeasonPage:
    """One Jikan seasonal page and the cursor required to continue it."""

    entries: list[dict[str, Any]]
    page: int
    has_next_page: bool


class JikanClient:
    """Fetch Jikan resources while respecting its public request limits.

    Rate-limit retries and transient server retries have separate budgets. A
    shared transient budget prevents a broad Jikan outage from multiplying a
    1,000-record job into thousands of slow retry requests.
    """

    def __init__(
        self,
        *,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        transient_retry_budget: int = MAX_TRANSIENT_RETRY_BUDGET,
    ) -> None:
        if transient_retry_budget < 0:
            raise ValueError("transient_retry_budget cannot be negative")
        self._opener = opener
        self._clock = clock
        self._sleeper = sleeper
        self._request_times: deque[float] = deque()
        self._last_request_time: float | None = None
        self._transient_retries_remaining = transient_retry_budget
        self._lock = threading.Lock()

    def get_anime_full(self, mal_id: int) -> dict[str, Any]:
        """Return full anime data, falling back to the basic endpoint."""
        self._validate_mal_id(mal_id)
        try:
            return self._get(
                f"/anime/{mal_id}/full",
                max_transient_retries=0,
                retry_network_errors=False,
            )
        except (HTTPError, JikanTemporaryError) as error:
            if (
                isinstance(error, HTTPError)
                and error.code not in SERVER_ERROR_STATUS_CODES
            ):
                raise
            return self.get_anime(mal_id)

    def get_anime(self, mal_id: int) -> dict[str, Any]:
        """Return basic anime data with one bounded 5xx/network retry."""
        self._validate_mal_id(mal_id)
        return self._get(
            f"/anime/{mal_id}",
            max_transient_retries=MAX_ANIME_TRANSIENT_RETRIES,
            retry_network_errors=True,
        )

    def get_season_page(
        self,
        year: int | None = None,
        season: str | None = None,
        *,
        page: int = 1,
    ) -> JikanSeasonPage:
        """Return one current or historical season page without hiding failures."""
        self._validate_season(year, season)
        if isinstance(page, bool) or not isinstance(page, int) or page <= 0:
            raise ValueError("page must be a positive integer")

        path = "/seasons/now" if year is None else f"/seasons/{year}/{season}"
        request_path = path if page == 1 else f"{path}?page={page}"
        payload = self._get(
            request_path,
            max_transient_retries=MAX_SEASON_TRANSIENT_RETRIES,
            retry_network_errors=True,
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("Jikan seasonal response did not contain an anime list")
        pagination = payload.get("pagination") or {}
        return JikanSeasonPage(
            entries=[entry for entry in data if isinstance(entry, dict)],
            page=page,
            has_next_page=bool(pagination.get("has_next_page")),
        )

    def get_season_anime(
        self, year: int | None = None, season: str | None = None
    ) -> list[dict[str, Any]]:
        """Return every anime listed for a current or specified season."""
        page = 1
        anime: list[dict[str, Any]] = []
        while True:
            result = self.get_season_page(year, season, page=page)
            anime.extend(result.entries)
            if not result.has_next_page:
                return anime
            page += 1

    def _get(
        self,
        path: str,
        *,
        max_transient_retries: int,
        retry_network_errors: bool,
    ) -> dict[str, Any]:
        """Fetch JSON with independent 429 and bounded transient retry budgets."""
        url = f"{BASE_URL}{path}"
        rate_retries = transient_retries = 0
        while True:
            self._throttle()
            request = Request(
                url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            )
            try:
                with self._opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code == 429 and rate_retries < MAX_429_RETRIES:
                    delay = self._retry_delay(error, rate_retries)
                    rate_retries += 1
                    error.close()
                    self._sleeper(delay)
                    continue
                if (
                    error.code in SERVER_ERROR_STATUS_CODES
                    and transient_retries < max_transient_retries
                    and self._claim_transient_retry()
                ):
                    delay = self._retry_delay(error, transient_retries)
                    transient_retries += 1
                    error.close()
                    self._sleeper(delay)
                    continue
                error.close()
                raise
            except (TimeoutError, URLError) as error:
                if (
                    retry_network_errors
                    and transient_retries < max_transient_retries
                    and self._claim_transient_retry()
                ):
                    self._sleeper(float(2**transient_retries))
                    transient_retries += 1
                    continue
                raise JikanTemporaryError(f"Jikan request failed: {path}") from error

    def _claim_transient_retry(self) -> bool:
        """Reserve one retry from the process-wide outage budget."""
        with self._lock:
            if self._transient_retries_remaining <= 0:
                return False
            self._transient_retries_remaining -= 1
            return True

    def _throttle(self) -> None:
        """Block until the request meets per-second and per-minute caps."""
        with self._lock:
            now = self._clock()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()

            delays = [0.0]
            if self._last_request_time is not None:
                delays.append(self._last_request_time + (1 / REQUESTS_PER_SECOND) - now)
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
    def _validate_mal_id(mal_id: int) -> None:
        if isinstance(mal_id, bool) or not isinstance(mal_id, int) or mal_id <= 0:
            raise ValueError("mal_id must be a positive integer")

    @staticmethod
    def _validate_season(year: int | None, season: str | None) -> None:
        if (year is None) != (season is None):
            raise ValueError("year and season must be supplied together")
        if season is not None and season not in {"winter", "spring", "summer", "fall"}:
            raise ValueError("season must be winter, spring, summer, or fall")

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


def get_anime(mal_id: int) -> dict[str, Any]:
    """Return the parsed Jikan v4 basic-anime payload for a MAL ID."""
    return _default_client.get_anime(mal_id)


def get_anime_full(mal_id: int) -> dict[str, Any]:
    """Return the parsed Jikan v4 full-anime payload for a MAL ID."""
    return _default_client.get_anime_full(mal_id)


def get_season_page(
    year: int | None = None,
    season: str | None = None,
    *,
    page: int = 1,
) -> JikanSeasonPage:
    """Return one parsed Jikan seasonal page."""
    return _default_client.get_season_page(year, season, page=page)


def get_season_anime(
    year: int | None = None, season: str | None = None
) -> list[dict[str, Any]]:
    """Return every anime from a current or specified season."""
    return _default_client.get_season_anime(year, season)

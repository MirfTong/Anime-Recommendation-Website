const DEFAULT_TTL_MS = 60_000;
const MAX_CACHE_ENTRIES = 80;

const getCache = new Map();
const inFlightRequests = new Map();
const SERVICE_UNAVAILABLE_MESSAGE = (
  "The catalogue is temporarily unavailable because its database cannot be reached. "
  + "Please try again shortly."
);

function cachedEntry(url, now) {
  const entry = getCache.get(url);
  if (!entry) return null;
  if (entry.expiresAt <= now) {
    getCache.delete(url);
    return null;
  }
  // Refresh insertion order so frequently reused pages stay in the bounded cache.
  getCache.delete(url);
  getCache.set(url, entry);
  return entry.result;
}

function remember(url, result, ttlMs) {
  getCache.delete(url);
  getCache.set(url, {
    expiresAt: Date.now() + ttlMs,
    result,
  });
  while (getCache.size > MAX_CACHE_ENTRIES) {
    getCache.delete(getCache.keys().next().value);
  }
}

export async function getJson(url, {
  signal,
  ttlMs = DEFAULT_TTL_MS,
  cache = true,
} = {}) {
  if (cache) {
    const existing = cachedEntry(url, Date.now());
    if (existing) return { ...existing, cached: true };
  }

  // Requests with an AbortSignal belong to a specific UI transition and must
  // remain independently cancellable. Cacheable background/detail requests
  // can safely share one in-flight fetch instead.
  const shareRequest = cache && !signal;
  let request = shareRequest ? inFlightRequests.get(url) : null;
  if (!request) {
    request = (async () => {
      let response;
      try {
        response = await fetch(url, { signal });
      } catch (error) {
        if (error?.name === "AbortError") throw error;
        throw new Error(SERVICE_UNAVAILABLE_MESSAGE, { cause: error });
      }
      let body;
      try {
        body = await response.json();
      } catch {
        body = {
          error: {
            message: response.status >= 500
              ? SERVICE_UNAVAILABLE_MESSAGE
              : "The server returned an invalid response. Please try again.",
          },
        };
      }
      const result = {
        ok: response.ok && !body.error,
        status: response.status,
        body,
      };
      if (cache && response.ok) remember(url, result, ttlMs);
      return result;
    })();
    if (shareRequest) inFlightRequests.set(url, request);
  }

  try {
    return { ...(await request), cached: false };
  } finally {
    if (shareRequest && inFlightRequests.get(url) === request) {
      inFlightRequests.delete(url);
    }
  }
}

export function clearGetCache() {
  getCache.clear();
  inFlightRequests.clear();
}

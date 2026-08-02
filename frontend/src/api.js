const DEFAULT_TTL_MS = 60_000;
const MAX_CACHE_ENTRIES = 80;

const getCache = new Map();

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

  const response = await fetch(url, { signal });
  const body = await response.json();
  const result = {
    ok: response.ok,
    status: response.status,
    body,
  };
  if (cache && response.ok) remember(url, result, ttlMs);
  return { ...result, cached: false };
}

export function clearGetCache() {
  getCache.clear();
}

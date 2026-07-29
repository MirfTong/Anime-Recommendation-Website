# KyoQuan Catalogue

<https://kyoquan.onrender.com/>

KyoQuan is a React single-page application backed by a Flask REST API and
PostgreSQL. It supports one searchable catalogue for Anime, Manga, and Manhwa,
with metadata populated incrementally from Tenrai and Jikan-compatible APIs.

## Architecture

```text
Tenrai/Jikan APIs
       |
       v
rate-limited Python client
       |
       v
resumable Anime + Manga/Manhwa ETL
       |
       v
PostgreSQL <-> Flask REST API <-> React/Vite frontend
```

The database keeps the existing `anime` table unchanged and adds a dedicated
`manga` table for both Manga and Manhwa. `manga.content_type` is constrained to
`MANGA` or `MANHWA`, while `mal_id` is unique because both types share
MyAnimeList's manga ID namespace. This avoids a risky rewrite of the deployed
anime schema while still providing a unified API.

Genres are normalized across all three content types:

- `genre` stores each genre name once.
- `anime_genre` connects Anime to genres.
- `manga_genre` connects Manga and Manhwa to the same genre rows.
- `genres_detailed` arrays retain searchable themes, demographics, explicit
  categories, and other detailed tags.

Frequently filtered score, year, type, season, status, chapter, volume, genre,
and tag columns have PostgreSQL indexes. The schema enables PostgreSQL's trusted
`pg_trgm` extension for indexed partial-title searches. Hentai and Erotica
records are rejected during discovery and detail refresh, removed during
cleanup, and excluded again from public API queries as defense in depth.

## Project layout

```text
backend/app.py                    Flask REST API and React build host
backend/models.py                 PostgreSQL ORM models and relationships
backend/schema.py                 safe additive schema setup
backend/services/jikan_client.py  shared provider client and request limiter
backend/jobs/jikan_etl.py         scheduled Anime + readable-title orchestration
backend/jobs/manga_etl.py         Manga/Manhwa discovery, refresh, and cleanup
frontend/src/App.jsx              React catalogue interface
tests/                            backend and ETL regression tests
.github/workflows/jikan-sync.yml  scheduled catalogue sync
```

## Local setup

1. Create `.env` from `.env.example` and set `DATABASE_URL` to PostgreSQL.
2. Install Python dependencies with `uv sync`, or use the included virtual
   environment.
3. Install and build the frontend:

   ```powershell
   npm --prefix frontend ci
   npm --prefix frontend run build
   ```

4. Run the API and React host:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.app
   ```

For production, build the frontend and start `gunicorn backend.app:app`.

## REST API

The canonical endpoints are:

- `GET /api/v1/catalogue` searches and filters the catalogue.
- `GET /api/v1/catalogue/random` returns a random selection.
- `GET /api/v1/catalogue/<content_type>/<mal_id>` returns full details.
- `GET /api/v1/genres` lists normalized genres.
- `GET /api/v1/tags` searches detailed tags.

Use `content_type=ANIME`, `MANGA`, `MANHWA`, or `ALL`. Common list filters are
`q`, `genre`, `tag`, `min_score`, `min_year`, `max_year`, `page`, and
`per_page`. Anime also supports `type`, `season`, and `min_episodes`. Manga and
Manhwa support `status`, `min_chapters`, and `min_volumes`.

The existing `/api/v1/anime`, `/api/v1/anime/random`,
`/api/v1/anime/seasonal`, and `/api/v1/anime/<mal_id>` routes remain available.
Convenience `/api/v1/manga` and `/api/v1/manhwa` list, random, and detail routes
are also provided.

## Provider client

`backend.services.jikan_client` uses Tenrai's Jikan-compatible v1 API as its
primary provider and public Jikan v4 as a fallback. Override the endpoints with
`ANIME_API_BASE_URL` and `ANIME_API_FALLBACK_BASE_URL`.

Anime and manga calls share one process-wide limiter capped at three requests
per second and 55 requests per minute. Temporary network failures and 5xx
responses have bounded retries; HTTP 429 responses honor a cooldown. Paginated
catalogue scans stay pinned to the primary provider so page boundaries cannot
change during a cursor-based run.

## ETL behavior

Run all scheduled phases locally with:

```powershell
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --scheduled-sync --page-limit 40 --limit 1000
```

The scheduled orchestration:

1. cleans stored adult-only records;
2. discovers current and historical Anime, including OVA, ONA, and Specials;
3. scans Manga and Manhwa catalogue pages independently;
4. refreshes Anime detail and missing-season queues;
5. refreshes the oldest-attempted Manga/Manhwa detail rows; and
6. reports coverage, failures, removals, and cursor progress.

Manga and Manhwa use separate persistent `jikan_sync_state` cursor keys. Each
successful page is committed with its next cursor, while a failed page remains
pending for a later run. A completed scan wraps to page 1 so new provider
records and changed listing metadata are discovered on future passes. Detail
refresh uses `last_jikan_attempt` ordering so missing, invalid, or temporarily
unavailable records are still marked attempted and cannot trap the queue.

Useful focused commands are:

```powershell
# Discover Manga and Manhwa catalogue pages
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --manga-catalogue --page-limit 40

# Refresh the next 1,000 readable-title details
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --refresh-manga --limit 1000

# Import the current Anime season
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --season current

# Refresh the existing Anime catalogue
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --limit 1000
```

## Scheduled GitHub Actions sync

`.github/workflows/jikan-sync.yml` runs every three hours and uses a concurrency
group so manual and scheduled jobs never write simultaneously. All phases run
inside one Python process, which preserves the shared rate limiter. The GitHub
Actions step summary reports Manga and Manhwa pages completed and failed,
records inserted and updated, adult records removed, and each independent next
page cursor, alongside the existing Anime metrics.

Add the external PostgreSQL URL as a repository Actions secret named
`DATABASE_URL` before running the workflow.

For Render, use:

```bash
npm --prefix frontend ci && npm --prefix frontend run build && pip install -r requirements.txt
```

## Tests

Run the complete backend suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Run the frontend production-build validation:

```powershell
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

The regression suite covers provider URLs and fallbacks, Manga/Manhwa mapping,
adult-content exclusion, duplicate-safe page application, independent cursors,
refresh-queue progression, API filtering, and workflow configuration.

## Tech stack

- Python, Flask, Flask-SQLAlchemy, SQLAlchemy, and PostgreSQL
- Tenrai v1 and Jikan v4-compatible APIs
- React, Vite, and Tailwind CSS
- GitHub Actions and Render

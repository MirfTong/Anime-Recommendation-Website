# Anime Recommendation Website

<https://kyoquan.onrender.com/>

A React single-page application backed by a Flask REST API for exploring an
anime catalogue by genre, rating, episode count, and other metadata. PostgreSQL
is the runtime data store, with Tenrai and Jikan-compatible catalogue sources.

## Project layout

```text
backend/             Flask application, models, API client, and sync jobs
frontend/            React and Vite source
tests/               Backend test suite
.github/workflows/   Scheduled catalogue sync
static/react/        Generated React build output (not committed)
```

## Local setup

1. Create `.env` from `.env.example` and set `DATABASE_URL`.
2. Install Python dependencies with `uv sync` (or use the included virtual
   environment).
3. Install and build the frontend:

   ```powershell
   npm --prefix frontend install
   npm --prefix frontend run build
   ```

4. Seed the catalogue from the current season:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --season current
   ```

5. Run the API and React host:

   ```powershell
   .\.venv\Scripts\python.exe -m backend.app
   ```

For production, use `gunicorn backend.app:app` after building the frontend.

## API

Flask serves the React application at `/`; its JSON API is available under
`/api/v1`:

- `GET /api/v1/anime` — paginated search and filters (`q`, `min_score`,
  `min_year`, `max_year`, `min_episodes`, `type`, `season`, and `genre`)
- `GET /api/v1/anime/random?limit=6` — random rated anime
- `GET /api/v1/anime/<mal_id>` — a detailed anime record
- `GET /api/v1/genres` — available genre filters

## Anime catalogue sync

The catalogue is populated and refreshed by `backend.jobs.jikan_etl`. To add
the current season, including sequels:

```powershell
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --season current
```

For a historical season, pass both its name and year, for example
`--season fall --year 2025`. To refresh the existing catalogue, run:

```powershell
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --limit 500
```

Missing TV season classifications are filled from a dedicated per-anime queue.
Every title is marked attempted even when the provider is temporarily
unavailable, so the next run advances instead of getting stuck:

```powershell
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --backfill-seasons --limit 1000
```

The scheduled workflow also scans 40 bulk catalogue pages per run, allowing up
to 1,000 records to be examined with only 40 requests:

```powershell
.\.venv\Scripts\python.exe -m backend.jobs.jikan_etl --bulk-seasons --page-limit 40
```

The client uses Tenrai's Jikan-compatible v1 API as its primary provider and
the public Jikan v4 API as a fallback. Override either endpoint with
`ANIME_API_BASE_URL` or `ANIME_API_FALLBACK_BASE_URL`. Calls remain limited to
three requests per second and 55 per minute, with bounded retries for temporary
gateway errors. Current-season and bulk imports commit one page at a time and
persist their cursors, so later failures do not discard successful pages.

## Scheduled sync

The GitHub Actions workflow runs every three hours. Each run resumes up to 10
pages of current-season discovery, scans 40 bulk catalogue pages, refreshes the
next 1,000 TV anime still missing season metadata, and refreshes the next 1,000
general catalogue records. Eight scheduled runs use roughly 16,000 detail
requests per day plus low-volume page requests, staying below the provider's
40,000-request public daily cap. The concurrency group keeps database writes
sequential. Before enabling it, add a repository Actions secret named
`DATABASE_URL` with the external PostgreSQL URL.

For Render, use this build command:

```bash
npm --prefix frontend ci && npm --prefix frontend run build && pip install -r requirements.txt
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Tech stack

- Python, Flask, Flask-SQLAlchemy, and PostgreSQL
- Tenrai v1 and Jikan v4-compatible anime APIs
- React, Vite, Tailwind CSS

# Anime Recommendation Website

<https://kyoquan.onrender.com/>

A React single-page application backed by a Flask REST API for exploring an
anime catalogue by genre, rating, episode count, and other metadata. PostgreSQL
is the runtime data store, and Jikan is the sole catalogue source.

## Project layout

```text
backend/             Flask application, models, Jikan client, and sync jobs
frontend/            React and Vite source
tests/               Backend test suite
.github/workflows/   Scheduled Jikan sync
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

## Jikan catalogue sync

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

Jikan calls are rate-limited. Each full-anime refresh also stores Jikan's
season classification (`winter`, `spring`, `summer`, or `fall`) when one is
available. Airing shows with an unknown score, year, or episode count are
stored with those fields empty until Jikan provides them.

## Scheduled sync

The GitHub Actions workflow runs every three hours. It imports the current
season and then refreshes the 500 anime that have gone longest without a Jikan
sync, including their season metadata. Before enabling it, add a repository
Actions secret named `DATABASE_URL` with the external PostgreSQL URL.

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
- Jikan v4 API
- React, Vite, Tailwind CSS

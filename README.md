# Anime Recommendation Website

https://kyoquan.onrender.com/

## About

A Flask web application for exploring anime by genres, ratings, episode counts,
and other metadata. PostgreSQL is the runtime data store; the cleaned CSV is
used only for the idempotent local import. Genres are stored in normalized
`genre` and `anime_genre` tables.

## Local setup

1. Create `.env` from `.env.example` and set `DATABASE_URL`.
2. Install dependencies with `uv sync` (or use the included virtual environment).
3. Create the schema and import the cleaned source data:

   ```powershell
   .\.venv\Scripts\python.exe import_anime.py
   ```

4. Run the app:

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

The importer can be run repeatedly. It updates existing anime by ID and uses
unique keys for genres and anime-genre associations, so it does not create
duplicates.

## Refreshing from Jikan

`jikan_etl.py` refreshes the anime already in PostgreSQL from Jikan's
rate-limited public API. Start with one known MyAnimeList ID:

```powershell
.\.venv\Scripts\python.exe jikan_etl.py --anime-id 1
```

To refresh the complete catalogue, run `.\.venv\Scripts\python.exe
jikan_etl.py`. The client honours Jikan's public limits, so a full refresh can
take several hours.

To discover and save anime from the current season, including season 2 and
later sequels, run:

```powershell
.\.venv\Scripts\python.exe jikan_etl.py --season current
```

For a historical season, specify both its name and year, for example
`--season fall --year 2025`. Airing shows with an unknown score, year, or
episode count are stored with those fields empty until Jikan provides them.

## Weekly GitHub Actions sync

The weekly workflow in `.github/workflows/jikan-sync.yml` imports the current
season and refreshes the 1,000 anime that have gone longest without a Jikan
sync. Each successful refresh updates its rating and timestamp, so later runs
rotate through the full catalogue.

The importer stores the CSV dataset row ID and the MyAnimeList ID separately.
Jikan requests always use the MyAnimeList ID parsed from `mal_url`.

Before enabling the workflow, add a repository Actions secret named
`DATABASE_URL` containing the external Render PostgreSQL URL. Do not commit
that URL to the repository.

## Tech stack

- Python and Flask
- Flask-SQLAlchemy / SQLAlchemy
- PostgreSQL
- HTML and CSS with Jinja templates
- CSV source: [User Anime List Dataset](https://www.kaggle.com/datasets/ramazanturann/user-animelist-dataset)

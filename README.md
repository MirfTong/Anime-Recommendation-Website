# Anime Recommendation Website

https://kyoquan.onrender.com/

## About

A Flask web application for exploring anime by genres, ratings, episode counts,
and other metadata. PostgreSQL is the runtime data store; the cleaned CSV is
used only for the one-time local import.

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

The importer will not overwrite an existing `anime` table. Empty the table
explicitly if a replacement import is intended.

## Tech stack

- Python and Flask
- Flask-SQLAlchemy / SQLAlchemy
- PostgreSQL
- HTML and CSS with Jinja templates
- CSV source: [User Anime List Dataset](https://www.kaggle.com/datasets/ramazanturann/user-animelist-dataset)

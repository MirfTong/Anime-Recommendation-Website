"""Idempotently import cleaned_animes.csv into the PostgreSQL schema."""

import ast
import csv
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app import app
from models import Anime, AnimeGenre, Genre, db

CSV_PATH = Path(__file__).with_name("cleaned_animes.csv")
MAL_ID_PATTERN = re.compile(r"/anime/(\d+)")


def parse_list(value: str) -> list[str]:
    return ast.literal_eval(value) if value else []


def parse_mal_id(mal_url: str) -> int:
    """Extract the MyAnimeList ID used by the Jikan API from a MAL URL."""
    match = MAL_ID_PATTERN.search(mal_url)
    if match is None:
        raise ValueError(f"Could not extract a MyAnimeList ID from {mal_url!r}")
    return int(match.group(1))


def import_anime() -> tuple[int, int]:
    """Create missing tables and upsert every CSV anime and its genres.

    Primary and unique constraints prevent duplicate anime, genre, and
    anime-genre records when this function is run more than once.
    """
    with app.app_context():
        db.create_all()
        anime_by_id = {
            anime.animeID: anime
            for anime in db.session.scalars(
                select(Anime).options(
                    selectinload(Anime.genre_links).selectinload(AnimeGenre.genre)
                )
            )
        }
        genre_by_name = {
            genre.name: genre for genre in db.session.scalars(select(Genre))
        }

        anime_count = 0
        with CSV_PATH.open(encoding="utf-8", newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                anime_id = int(row["animeID"])
                genres = parse_list(row["genres"])
                anime = anime_by_id.get(anime_id)
                fields = {
                    "mal_id": parse_mal_id(row["mal_url"]),
                    "title": row["title"],
                    "alternative_title": row["alternative_title"] or None,
                    "type": row["type"],
                    "year": int(row["year"]),
                    "score": float(row["score"]),
                    "episodes": int(row["episodes"]),
                    "mal_url": row["mal_url"],
                    "sequel": row["sequel"].strip().lower() == "true",
                    "image_url": row["image_url"],
                    "legacy_genres": genres,
                    "genres_detailed": parse_list(row["genres_detailed"]),
                }
                if anime is None:
                    anime = Anime(animeID=anime_id, **fields)
                    db.session.add(anime)
                    anime_by_id[anime_id] = anime
                else:
                    for field, value in fields.items():
                        setattr(anime, field, value)

                links_by_name = {link.genre.name: link for link in anime.genre_links}
                wanted_names = set(genres)
                for name in wanted_names:
                    genre = genre_by_name.get(name)
                    if genre is None:
                        genre = Genre(name=name)
                        db.session.add(genre)
                        genre_by_name[name] = genre
                    if name not in links_by_name:
                        anime.genre_links.append(AnimeGenre(genre=genre))
                for name, link in links_by_name.items():
                    if name not in wanted_names:
                        db.session.delete(link)
                anime_count += 1

        db.session.commit()
        return anime_count, len(genre_by_name)


if __name__ == "__main__":
    anime_count, genre_count = import_anime()
    print(f"Imported {anime_count} anime records and {genre_count} genres into PostgreSQL.")

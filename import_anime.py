"""Create the schema and import the cleaned CSV into PostgreSQL."""

import ast
import csv
from pathlib import Path

from sqlalchemy import select

from app import app
from models import Anime, db

CSV_PATH = Path(__file__).with_name("cleaned_animes.csv")
BATCH_SIZE = 500


def parse_list(value: str) -> list[str]:
    return ast.literal_eval(value) if value else []


def import_anime() -> int:
    with app.app_context():
        db.create_all()
        if db.session.scalar(select(Anime.animeID).limit(1)) is not None:
            raise RuntimeError(
                "The anime table already contains data. Empty it explicitly before rerunning this importer."
            )

        total = 0
        batch: list[Anime] = []
        with CSV_PATH.open(encoding="utf-8", newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                batch.append(
                    Anime(
                        animeID=int(row["animeID"]),
                        title=row["title"],
                        alternative_title=row["alternative_title"] or None,
                        type=row["type"],
                        year=int(row["year"]),
                        score=float(row["score"]),
                        episodes=int(row["episodes"]),
                        mal_url=row["mal_url"],
                        sequel=row["sequel"].strip().lower() == "true",
                        image_url=row["image_url"],
                        genres=parse_list(row["genres"]),
                        genres_detailed=parse_list(row["genres_detailed"]),
                    )
                )
                if len(batch) == BATCH_SIZE:
                    db.session.add_all(batch)
                    db.session.commit()
                    total += len(batch)
                    batch.clear()

        if batch:
            db.session.add_all(batch)
            db.session.commit()
            total += len(batch)
        return total


if __name__ == "__main__":
    count = import_anime()
    print(f"Imported {count} anime records into PostgreSQL.")

"""Legacy entry point for the PostgreSQL dataset import."""

from import_anime import import_anime


if __name__ == "__main__":
    count = import_anime()
    print(f"Imported {count} anime records into PostgreSQL.")

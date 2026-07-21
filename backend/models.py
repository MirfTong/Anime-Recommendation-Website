from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from flask_sqlalchemy import SQLAlchemy


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Anime(db.Model):
    __tablename__ = "anime"
    __table_args__ = (
        Index("ix_anime_score_year", "score", "year"),
        Index("ix_anime_type_score", "type", "score"),
        Index("ix_anime_season_score", "season", "score"),
    )

    animeID: Mapped[int] = mapped_column("anime_id", primary_key=True)
    # The CSV's anime_id is a dataset row ID. Jikan must use this separate
    # MyAnimeList ID instead.
    mal_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    title: Mapped[str] = mapped_column(index=True)
    alternative_title: Mapped[str | None]
    type: Mapped[str] = mapped_column(index=True)
    # Jikan returns one of winter, spring, summer, fall, or no season.
    season: Mapped[str | None] = mapped_column(String(6), index=True)
    # Airing and unreleased anime may not have these values yet.
    year: Mapped[int | None] = mapped_column(index=True)
    score: Mapped[float | None] = mapped_column(index=True)
    episodes: Mapped[int | None] = mapped_column(index=True)
    last_jikan_sync: Mapped[datetime | None] = mapped_column(index=True)
    mal_url: Mapped[str]
    sequel: Mapped[bool]
    image_url: Mapped[str]

    # Retained for compatibility with the existing anime table. The normalized
    # genre tables below are the source of truth for application queries.
    legacy_genres: Mapped[list[str]] = mapped_column("genres", ARRAY(String))
    genres_detailed: Mapped[list[str]] = mapped_column(ARRAY(String))

    genre_links: Mapped[list["AnimeGenre"]] = relationship(
        back_populates="anime", cascade="all, delete-orphan"
    )
    genre_entries: Mapped[list["Genre"]] = relationship(
        secondary="anime_genre", viewonly=True, lazy="selectin"
    )

    @property
    def genres(self) -> list[str]:
        """Genre names for template rendering."""
        return [genre.name for genre in self.genre_entries]


class Genre(db.Model):
    __tablename__ = "genre"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    anime_links: Mapped[list["AnimeGenre"]] = relationship(
        back_populates="genre", cascade="all, delete-orphan"
    )
    anime_entries: Mapped[list[Anime]] = relationship(
        secondary="anime_genre", viewonly=True, lazy="selectin"
    )


class AnimeGenre(db.Model):
    __tablename__ = "anime_genre"

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.anime_id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(
        ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True
    )

    anime: Mapped[Anime] = relationship(back_populates="genre_links")
    genre: Mapped[Genre] = relationship(back_populates="anime_links")

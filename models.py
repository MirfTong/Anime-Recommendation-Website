from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from flask_sqlalchemy import SQLAlchemy


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Anime(db.Model):
    __tablename__ = "anime"

    animeID: Mapped[int] = mapped_column("anime_id", primary_key=True)
    title: Mapped[str] = mapped_column(index=True)
    alternative_title: Mapped[str | None]
    type: Mapped[str] = mapped_column(index=True)
    # Airing and unreleased anime may not have these values yet.
    year: Mapped[int | None] = mapped_column(index=True)
    score: Mapped[float | None] = mapped_column(index=True)
    episodes: Mapped[int | None] = mapped_column(index=True)
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

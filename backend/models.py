from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
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
        Index("ix_anime_public_score", "is_adult", "score"),
        Index("ix_anime_type_score", "type", "score"),
        Index("ix_anime_season_score", "season", "score"),
        Index(
            "ix_anime_genres_detailed_gin",
            "genres_detailed",
            postgresql_using="gin",
        ),
        Index(
            "ix_anime_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_anime_alternative_title_trgm",
            "alternative_title",
            postgresql_using="gin",
            postgresql_ops={"alternative_title": "gin_trgm_ops"},
        ),
    )

    animeID: Mapped[int] = mapped_column("anime_id", primary_key=True)
    # The CSV's anime_id is a dataset row ID. Jikan must use this separate
    # MyAnimeList ID instead.
    mal_id: Mapped[int | None] = mapped_column(unique=True, index=True)
    title: Mapped[str] = mapped_column(index=True)
    alternative_title: Mapped[str | None]
    synopsis: Mapped[str | None]
    type: Mapped[str] = mapped_column(index=True)
    # Jikan returns one of winter, spring, summer, fall, or no season.
    season: Mapped[str | None] = mapped_column(String(6), index=True)
    # Airing and unreleased anime may not have these values yet.
    year: Mapped[int | None] = mapped_column(index=True)
    score: Mapped[float | None] = mapped_column(index=True)
    is_adult: Mapped[bool] = mapped_column(
        default=False, server_default="false", index=True
    )
    episodes: Mapped[int | None] = mapped_column(index=True)
    last_jikan_sync: Mapped[datetime | None] = mapped_column(index=True)
    last_season_attempt: Mapped[datetime | None] = mapped_column(index=True)
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
        secondary="anime_genre", viewonly=True
    )
    manga_links: Mapped[list["MangaGenre"]] = relationship(
        back_populates="genre", cascade="all, delete-orphan"
    )
    manga_entries: Mapped[list["Manga"]] = relationship(
        secondary="manga_genre", viewonly=True
    )


class AnimeGenre(db.Model):
    __tablename__ = "anime_genre"
    __table_args__ = (
        Index("ix_anime_genre_genre_anime", "genre_id", "anime_id"),
    )

    anime_id: Mapped[int] = mapped_column(
        ForeignKey("anime.anime_id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(
        ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True
    )

    anime: Mapped[Anime] = relationship(back_populates="genre_links")
    genre: Mapped[Genre] = relationship(back_populates="anime_links")


class Manga(db.Model):
    """A readable-title catalogue row sourced from Jikan's manga API."""

    __tablename__ = "manga"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ('MANGA', 'MANHWA')",
            name="ck_manga_content_type",
        ),
        Index("ix_manga_content_score", "content_type", "score"),
        Index(
            "ix_manga_content_public_score",
            "content_type",
            "is_adult",
            "score",
        ),
        Index("ix_manga_content_year", "content_type", "publication_year"),
        Index("ix_manga_content_chapters", "content_type", "chapters"),
        Index("ix_manga_content_volumes", "content_type", "volumes"),
        Index("ix_manga_content_status_score", "content_type", "status", "score"),
        Index(
            "ix_manga_genres_detailed_gin",
            "genres_detailed",
            postgresql_using="gin",
        ),
        Index(
            "ix_manga_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_manga_alternative_title_trgm",
            "alternative_title",
            postgresql_using="gin",
            postgresql_ops={"alternative_title": "gin_trgm_ops"},
        ),
    )

    mangaID: Mapped[int] = mapped_column("manga_id", primary_key=True)
    mal_id: Mapped[int] = mapped_column(unique=True, index=True)
    content_type: Mapped[str] = mapped_column(String(10), index=True)
    title: Mapped[str] = mapped_column(index=True)
    alternative_title: Mapped[str | None]
    synopsis: Mapped[str | None]
    manga_type: Mapped[str | None] = mapped_column(String(30), index=True)
    publication_year: Mapped[int | None] = mapped_column(index=True)
    status: Mapped[str | None] = mapped_column(String(50), index=True)
    score: Mapped[float | None] = mapped_column(index=True)
    is_adult: Mapped[bool] = mapped_column(
        default=False, server_default="false", index=True
    )
    chapters: Mapped[int | None] = mapped_column(index=True)
    volumes: Mapped[int | None] = mapped_column(index=True)
    mal_url: Mapped[str]
    image_url: Mapped[str]
    last_jikan_sync: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_jikan_attempt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    legacy_genres: Mapped[list[str]] = mapped_column(
        "genres", ARRAY(String), default=list, server_default="{}"
    )
    genres_detailed: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}"
    )

    genre_links: Mapped[list["MangaGenre"]] = relationship(
        back_populates="manga", cascade="all, delete-orphan"
    )
    genre_entries: Mapped[list[Genre]] = relationship(
        secondary="manga_genre", viewonly=True, lazy="selectin"
    )

    @property
    def genres(self) -> list[str]:
        return [genre.name for genre in self.genre_entries]


class MangaGenre(db.Model):
    """Many-to-many connection between readable titles and shared genres."""

    __tablename__ = "manga_genre"
    __table_args__ = (
        Index("ix_manga_genre_genre_manga", "genre_id", "manga_id"),
    )

    manga_id: Mapped[int] = mapped_column(
        ForeignKey("manga.manga_id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[int] = mapped_column(
        ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True
    )

    manga: Mapped[Manga] = relationship(back_populates="genre_links")
    genre: Mapped[Genre] = relationship(back_populates="manga_links")


class CatalogueFacet(db.Model):
    """Precomputed genre and tag options for one public content type."""

    __tablename__ = "catalogue_facet"
    __table_args__ = (
        CheckConstraint(
            "content_type IN ('ANIME', 'MANGA', 'MANHWA')",
            name="ck_catalogue_facet_content_type",
        ),
        CheckConstraint(
            "facet_type IN ('genre', 'tag')",
            name="ck_catalogue_facet_type",
        ),
    )

    content_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    facet_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), primary_key=True)


class JikanSyncState(db.Model):
    """Persistent cursor and health state for resumable Jikan page imports."""

    __tablename__ = "jikan_sync_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    next_page: Mapped[int] = mapped_column(default=1)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

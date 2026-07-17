from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)


class Anime(db.Model):
    __tablename__ = "anime"

    animeID: Mapped[int] = mapped_column("anime_id", primary_key=True)
    title: Mapped[str] = mapped_column(index=True)
    alternative_title: Mapped[str | None]
    type: Mapped[str] = mapped_column(index=True)
    year: Mapped[int] = mapped_column(index=True)
    score: Mapped[float] = mapped_column(index=True)
    episodes: Mapped[int] = mapped_column(index=True)
    mal_url: Mapped[str]
    sequel: Mapped[bool]
    image_url: Mapped[str]
    genres: Mapped[list[str]] = mapped_column(ARRAY(String), index=True)
    genres_detailed: Mapped[list[str]] = mapped_column(ARRAY(String))

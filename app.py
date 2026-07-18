import os

from dotenv import load_dotenv
from flask import Flask, render_template, request
from sqlalchemy import func, or_, select

from models import Anime, Genre, db

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["DATABASE_URL"]
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)


@app.route("/random-anime")
def random_anime():
    anime_list = db.session.scalars(
        select(Anime)
        .where(Anime.score.is_not(None))
        .order_by(func.random())
        .limit(6)
    ).all()
    return render_template("index.html", anime=anime_list)


@app.route("/")
def anime():
    query = request.args.get("search", "").strip()
    eps = request.args.get("eps", type=int)
    score = request.args.get("score", type=float)
    year = request.args.get("year", type=int)
    types = request.args.getlist("type")
    genres = request.args.getlist("genre")

    genre_list = db.session.scalars(
        select(Genre.name).where(Genre.name != "Hentai").order_by(Genre.name)
    ).all()

    # Unreleased shows often have no score yet and should not appear in
    # recommendation/browse cards until Jikan publishes one.
    statement = select(Anime).where(Anime.score.is_not(None))
    has_filters = any((eps, score, year, types, genres))

    if query:
        escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_query}%"
        statement = statement.where(
            or_(
                Anime.title.ilike(pattern, escape="\\"),
                Anime.alternative_title.ilike(pattern, escape="\\"),
            )
        )
    if eps:
        statement = statement.where(Anime.episodes >= eps)
    if score:
        statement = statement.where(Anime.score >= score)
    if year:
        statement = statement.where(Anime.year <= year)
    if types:
        statement = statement.where(Anime.type.in_(types))
    for genre in genres:
        statement = statement.where(Anime.genre_entries.any(Genre.name == genre))

    if not query and not has_filters:
        statement = statement.order_by(Anime.score.desc()).offset(1).limit(100)
    else:
        statement = statement.order_by(Anime.score.desc())

    anime_list = db.session.scalars(statement).all()
    message = None
    if (query or has_filters) and not anime_list:
        message = f"No results found for '{query}'" if query else "No results found"

    return render_template(
        "index1.html",
        anime=anime_list,
        message=message,
        genre=genre_list,
        query=query,
        eps=eps,
        score=score,
        year=year,
    )


if __name__ == "__main__":
    app.run(debug=True, port=8000)

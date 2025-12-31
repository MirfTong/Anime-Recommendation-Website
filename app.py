from flask import Flask, render_template, url_for, request
import pandas as pd
import ast

app = Flask(__name__)
df = pd.read_csv("cleaned_animes.csv")

@app.route("/random-anime")
def random_anime(): 
    anime_list = df.sample(n=6)
    anime_list = anime_list.to_dict(orient='records')

    anime_list = clean_alternative_titles(anime_list)

    return render_template('index.html', anime=anime_list)

@app.route("/home")
def anime():
    query = request.args.get("search","").lower()
    message = None
    eps = request.args.get("eps", 0, type=int)
    score = request.args.get("score", 0, type=float)
    year = request.args.get("year", 0, type=int)
    types = request.args.getlist("type")
    genre = request.args.getlist("genre")

    genre_list = df["genres"].apply(ast.literal_eval).explode().dropna().str.strip().unique()
    genre_list = genre_list[genre_list != "Hentai"]
    genre_list.sort()

    if query:
        anime_list = df[
            df["title"].str.lower().str.contains(query, na=False, regex=False) | 
            df["alternative_title"].str.lower().str.contains(query, na=False, regex=False)]

        if anime_list.empty:
            message = f"No results found for '{query}'"

        if eps:
            anime_list = anime_list[anime_list["episodes"] >= eps]
        if score:
            anime_list = anime_list[anime_list["score"] >= score]
        if year:
            anime_list = anime_list[anime_list["year"] <= year]
        if types:
            anime_list = anime_list[anime_list["type"].isin(types)]
        if genre:
            for g in genre:
                anime_list = anime_list[anime_list["genres"].str.contains(g)]

    else:   
        anime_list = df
        
        if (eps or score or year or types or genre):
            if eps:
                anime_list = anime_list[anime_list["episodes"] >= eps]
            if score:
                anime_list = anime_list[anime_list["score"] >= score]
            if year:
                anime_list = anime_list[anime_list["year"] <= year]
            if types:
                anime_list = anime_list[anime_list["type"].isin(types)]
            if genre:
                for g in genre: 
                    anime_list = anime_list[anime_list["genres"].str.contains(g)]

        else: 
            anime_list = df.sort_values(by="score", ascending=False)[:101].iloc[1:]
            
    anime_list = anime_list.sort_values(by="score", ascending=False)
    anime_list = anime_list.to_dict(orient='records')
    anime_list = clean_alternative_titles(anime_list)

    return render_template('index1.html', anime=anime_list, message=message, genre=genre_list)

def clean_alternative_titles(clean_list):
    for data in clean_list:
        if pd.isna(data.get("alternative_title")):
            data["alternative_title"] = ""
    return clean_list

if __name__ == '__main__':
    app.run(debug=True, port=8000)
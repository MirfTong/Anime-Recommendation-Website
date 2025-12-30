from flask import Flask, render_template, url_for, request
import pandas as pd

app = Flask(__name__)
df = pd.read_csv("cleaned_animes.csv")

# Page
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
    score = request.args.get("score", 0, type=int)

    if query:
        anime_list = df[
            df["title"].str.lower().str.contains(query, na=False, regex=False) | 
            df["alternative_title"].str.lower().str.contains(query, na=False, regex=False)]
        # anime_list = anime_list.to_dict(orient="records")
        if anime_list.empty:
            message = f"No results found for '{query}'"

    else:
        # anime_list = df.nlargest(21, "score")
        anime_list = df.sort_values(by="score", ascending=False)[:100].iloc[1:]
        
        
        if eps:
            anime_list = df[df["episodes"] >= eps]
            # anime_list.drop(df[df["episodes"] < eps].index, inplace=True)

        if score:
            anime_list = df[df["score"] >= score]
            # anime_list.drop(df[df["score"] < score].index, inplace=True)

        if (eps > 0) & (score >= 7):
            anime_list = df[(df["episodes"] >= eps) & (df["score"] >= score)]

        # TODO: Filters for TV/Movie, Year, & Genres
    
    anime_list = anime_list.to_dict(orient='records')
    anime_list = clean_alternative_titles(anime_list)

    return render_template('index1.html', anime=anime_list, message=message)

def clean_alternative_titles(clean_list):
    for data in clean_list:
        if pd.isna(data.get("alternative_title")):
            data["alternative_title"] = ""
    return clean_list

if __name__ == '__main__':
    app.run(debug=True, port=8000)
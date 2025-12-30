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
    if query:
        anime_list = df[
            df["title"].astype(str).str.lower().str.contains(query, na=False, regex=False) | 
            df["alternative_title"].astype(str).str.lower().str.contains(query, na=False, regex=False)]
        anime_list = anime_list.to_dict(orient="records")
    else:
        # anime_list = df.nlargest(21, "score")
        anime_list = df.sort_values(by="score", ascending=False)[:100].iloc[1:]
        anime_list = anime_list.to_dict(orient='records')

    anime_list = clean_alternative_titles(anime_list)
    return render_template('index1.html', anime=anime_list)

def clean_alternative_titles(clean_list):
    for data in clean_list:
        if pd.isna(data.get("alternative_title")):
            data["alternative_title"] = ""
    return clean_list

if __name__ == '__main__':
    app.run(debug=True, port=8000)
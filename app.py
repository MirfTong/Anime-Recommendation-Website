from flask import Flask, render_template, url_for
import pandas as pd

app = Flask(__name__)
df = pd.read_csv("cleaned_animes.csv")

# Page
@app.route("/random-anime")
def random_anime(): 
    random_df = df.sample(n=6)
    random_df = random_df.to_dict(orient='records')

    for data in random_df:
        for key, value in data.items():
            if key == "alternative_title":
                if pd.isna(value):
                    data[key] = ""

    return render_template('index.html', anime=random_df)

@app.route("/anime")
def anime():
    return render_template('index1.html', anime=df)

if __name__ == '__main__':
    app.run(debug=True, port=8000)
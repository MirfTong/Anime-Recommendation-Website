import pandas as pd

df = pd.read_csv("animes.csv")
print(df["genres_detailed"])
import pandas as pd

df = pd.read_csv("animes.csv")

# Cleaning data
df.drop(df[df["type"] == "ONA"].index, inplace=True)
df.drop(df[df["type"] == "OVA"].index, inplace=True)
df.drop(df[df["type"] == "SPECIAL"].index, inplace=True)

df.drop(df[df["score"] == '?'].index, inplace=True)
df["score"] = df["score"].astype(float)
df.drop(df[df["score"] < 7].index, inplace=True)

df.drop(df[df["year"] == '?'].index, inplace=True)
df["year"] = df["year"].astype (int)

df.drop(df[df["genres"] == "['Hentai']"].index, inplace=True) 

df.drop(df[df["animeID"] == 8020].index, inplace=True) # One Punch Man S3

df.to_csv("cleaned_animes.csv", index=False)
import requests
import pandas as pd
import os

print("Downloading Paris DVF data...")

url = "https://files.data.gouv.fr/geo-dvf/latest/csv/2024/departements/75.csv.gz"
response = requests.get(url)

with open("paris_transactions.csv.gz", "wb") as f:
    f.write(response.content)

print("Downloaded. Loading...")

df = pd.read_csv("paris_transactions.csv.gz", compression="gzip")
print(f"Total rows: {len(df)}")
print(f"Columns: {list(df.columns)}")
print(df.head(3))

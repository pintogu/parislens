import pandas as pd

df = pd.read_csv("paris_transactions.csv.gz", compression="gzip", low_memory=False)

# Keep only apartment sales
df = df[df["type_local"] == "Appartement"]
df = df[df["nature_mutation"] == "Vente"]

print(f"Apartment sales: {len(df)}")
print(f"\nKey columns:")
print(df[["date_mutation", "valeur_fonciere", "surface_reelle_bati", 
          "nombre_pieces_principales", "code_postal"]].head(10))

print(f"\nSample prices: {df['valeur_fonciere'].dropna().head(5).tolist()}")
print(f"Sample surfaces: {df['surface_reelle_bati'].dropna().head(5).tolist()}")
print(f"Sample postcodes: {df['code_postal'].dropna().head(5).tolist()}")

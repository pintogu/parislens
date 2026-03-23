import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

print("Loading DVF data...")
df = pd.read_csv("paris_transactions.csv.gz", compression="gzip", low_memory=False)

df = df[df["type_local"] == "Appartement"]
df = df[df["nature_mutation"] == "Vente"]
df = df.dropna(subset=["valeur_fonciere", "surface_reelle_bati", "code_postal"])
df = df.sort_values("surface_reelle_bati", ascending=False)
df = df.drop_duplicates(subset=["id_mutation"], keep="first")
df["price_per_m2"] = df["valeur_fonciere"] / df["surface_reelle_bati"]
df = df[df["surface_reelle_bati"] >= 10]
df = df[df["surface_reelle_bati"] <= 500]
df = df[df["price_per_m2"] >= 3000]
df = df[df["price_per_m2"] <= 40000]

print(f"Clean transactions: {len(df)}")

conn = psycopg2.connect(os.environ["DATABASE_URL"])
cur = conn.cursor()

# Wipe old bad data
print("Clearing old data...")
cur.execute("TRUNCATE bronze_listings, silver_listings, gold_daily_stats RESTART IDENTITY CASCADE")
conn.commit()

# Load fresh
saved = 0
for _, row in df.iterrows():
    try:
        arrondissement = str(int(row["code_postal"]))
        price_raw = str(int(row["valeur_fonciere"])) + " €"
        surface_raw = str(row["surface_reelle_bati"]) + " m²"
        rooms = int(row["nombre_pieces_principales"]) if pd.notna(row["nombre_pieces_principales"]) else None
        url = f"dvf-{row['id_mutation']}-{arrondissement}"

        cur.execute("""
            INSERT INTO bronze_listings
              (title, price_raw, surface_raw, arrondissement, url, scraped_at)
            VALUES (%s, %s, %s, %s, %s, %s::date)
            ON CONFLICT (url) DO NOTHING
        """, (f"Appartement {arrondissement}", price_raw, surface_raw,
              arrondissement, url, row["date_mutation"]))

        if cur.rowcount > 0:
            saved += 1
    except Exception as e:
        pass

    if saved % 2000 == 0 and saved > 0:
        conn.commit()
        print(f"  {saved} rows saved...")

conn.commit()
cur.close()
conn.close()
print(f"\n✅ Done — {saved} rows in Bronze")

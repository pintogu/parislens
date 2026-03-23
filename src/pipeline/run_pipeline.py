import os
import psycopg2
import pandas as pd
from dotenv import load_dotenv
from datetime import date

load_dotenv()

def download_and_load():
    import requests
    print("📥 Downloading latest DVF data...")
    url = "https://files.data.gouv.fr/geo-dvf/latest/csv/2024/departements/75.csv.gz"
    response = requests.get(url)
    with open("paris_transactions.csv.gz", "wb") as f:
        f.write(response.content)
    print("✅ Downloaded")

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

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    saved = 0
    for _, row in df.iterrows():
        try:
            arrondissement = str(int(row["code_postal"]))
            url_key = f"dvf-{row['id_mutation']}-{arrondissement}"
            cur.execute("""
                INSERT INTO bronze_listings
                  (title, price_raw, surface_raw, arrondissement, url, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s::date)
                ON CONFLICT (url) DO NOTHING
            """, (f"Appartement {arrondissement}",
                  str(int(row["valeur_fonciere"])) + " €",
                  str(row["surface_reelle_bati"]) + " m²",
                  arrondissement, url_key, row["date_mutation"]))
            if cur.rowcount > 0:
                saved += 1
        except:
            pass
        if saved % 2000 == 0 and saved > 0:
            conn.commit()
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Bronze: {saved} new rows loaded")
    return saved

def bronze_to_silver():
    import re
    def parse_price(raw):
        digits = re.sub(r"[^\d]", "", raw or "")
        return int(digits) if digits else None
    def parse_surface(raw):
        match = re.search(r"([\d,\.]+)\s*m", raw or "")
        return float(match.group(1).replace(",", ".")) if match else None

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT id, price_raw, surface_raw, arrondissement FROM bronze_listings WHERE processed = FALSE")
    rows = cur.fetchall()
    cleaned = 0
    for row in rows:
        id_, price_raw, surface_raw, arr = row
        price = parse_price(price_raw)
        surface = parse_surface(surface_raw)
        if not price or not surface or surface == 0:
            cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
            continue
        price_per_m2 = round(price / surface, 2)
        cur.execute("""
            INSERT INTO silver_listings
              (bronze_id, price_eur, surface_m2, price_per_m2, arrondissement, scraped_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (id_, price, surface, price_per_m2, arr))
        cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
        cleaned += 1
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Silver: {cleaned} rows cleaned")

def silver_to_gold():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO gold_daily_stats (arrondissement, date, avg_price_per_m2, listing_count)
        SELECT
            arrondissement,
            CURRENT_DATE,
            ROUND(AVG(price_per_m2)::numeric, 2),
            COUNT(*)
        FROM silver_listings
        GROUP BY arrondissement
        ON CONFLICT (arrondissement, date) DO UPDATE
          SET avg_price_per_m2 = EXCLUDED.avg_price_per_m2,
              listing_count = EXCLUDED.listing_count,
              computed_at = NOW()
    """)
    # Log this run
    cur.execute("""
        INSERT INTO scraper_runs (status, listings_added)
        VALUES ('success', (SELECT COUNT(*) FROM bronze_listings WHERE scraped_at::date = CURRENT_DATE))
    """)
    conn.commit()
    cur.close()
    conn.close()
    print(f"✅ Gold: updated for {date.today()}")

if __name__ == "__main__":
    print(f"\n🚀 Pipeline starting — {date.today()}\n")
    try:
        download_and_load()
        bronze_to_silver()
        silver_to_gold()
        print("\n🎉 Pipeline complete!\n")
    except Exception as e:
        # Log failure
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("INSERT INTO scraper_runs (status, listings_added) VALUES ('failed', 0)")
        conn.commit()
        conn.close()
        print(f"\n❌ Pipeline failed: {e}\n")
        raise

import os
import re
import requests
import psycopg2
import pandas as pd
from dotenv import load_dotenv
import datetime
from datetime import date
from logger import get_logger  
load_dotenv()

logger = get_logger("parislens") 

# Load to base de donnees and download data

def download_and_load():
    logger.info("Downloading latest DVF data...")
    current_year = datetime.date.today().year
    url = f"https://files.data.gouv.fr/geo-dvf/latest/csv/{current_year}/departements/75.csv.gz"

    response = requests.get(url, timeout=60)

    if response.status_code == 404:
        fallback_year = current_year - 1
        logger.warning(f"No data found for {current_year}, falling back to {fallback_year}")
        url = f"https://files.data.gouv.fr/geo-dvf/latest/csv/{fallback_year}/departements/75.csv.gz"
        response = requests.get(url, timeout=60)

    response.raise_for_status()
    # Save the file to disk
    with open("paris_transactions.csv.gz", "wb") as f:
        f.write(response.content)

    logger.info(f"DVF file downloaded successfully (year: {url.split('/')[7]})")

    df = pd.read_csv("paris_transactions.csv.gz", compression="gzip", low_memory=False)
    logger.info(f"DVF file downloaded successfully (year: {url.split('/')[7]})")

    df = pd.read_csv("paris_transactions.csv.gz", compression="gzip", low_memory=False)
    logger.info(f"Loaded {len(df)} raw rows from CSV")

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
    logger.info(f"{len(df)} rows remaining after filtering")

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    saved = 0

    for _, row in df.iterrows():
        try:
            arrondissement = str(int(row["code_postal"]))
            url_key = f"dvf-{row['id_mutation']}-{arrondissement}"
            cur.execute("""
                INSERT INTO bronze_listings
                  (title, price_raw, surface_raw, arrondissement, rooms_raw, longitude_raw, latitude_raw, url, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::date)
                ON CONFLICT (url) DO NOTHING
            """, (
                f"Appartement {arrondissement}",
                str(int(row["valeur_fonciere"])) + " €",
                str(row["surface_reelle_bati"]) + " m²",
                arrondissement,
                str(row["nombre_pieces_principales"]) if pd.notna(row["nombre_pieces_principales"]) else None,
                str(row["longitude"]) if pd.notna(row["longitude"]) else None,
                str(row["latitude"]) if pd.notna(row["latitude"]) else None,
                url_key,
                row["date_mutation"]
            ))
            if cur.rowcount > 0:
                saved += 1
        except Exception as e:
            logger.warning(f"Skipping row {row.get('id_mutation')}: {e}")

        if saved % 2000 == 0 and saved > 0:
            conn.commit()
            logger.info(f"{saved} rows committed so far...")

    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Bronze: {saved} new rows loaded")
    return saved


def bronze_to_silver():
    def parse_price(raw):
        digits = re.sub(r"[^\d]", "", raw or "")
        return int(digits) if digits else None

    def parse_surface(raw):
        match = re.search(r"([\d,\.]+)\s*m", raw or "")
        return float(match.group(1).replace(",", ".")) if match else None
    
    def parse_rooms(raw):
        try:
            val = float(raw)
            # enforce integer-like values only
            if not val.is_integer():
                return None
            return int(val)
        except (ValueError, TypeError):
            return None

    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT id, price_raw, surface_raw, arrondissement, rooms_raw, longitude_raw, latitude_raw FROM bronze_listings WHERE processed = FALSE")
    rows = cur.fetchall()
    logger.info(f"Bronze to Silver: {len(rows)} unprocessed rows found")

    cleaned = 0
    try:
        for row in rows:
            id_, price_raw, surface_raw, arr, rooms_raw, longitude_raw, latitude_raw = row
            price = parse_price(price_raw)
            surface = parse_surface(surface_raw)
            rooms = parse_rooms(rooms_raw)
            longitude = float(longitude_raw) if longitude_raw else None
            latitude = float(latitude_raw) if latitude_raw else None

            if not price or not surface or surface == 0:
                logger.warning(f"Skipping bronze id={id_}: could not parse price or surface")
                cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
                continue


            price_per_m2 = round(price / surface, 2)
            cur.execute("""
                INSERT INTO silver_listings
                  (bronze_id, price_eur, surface_m2, price_per_m2, arrondissement, rooms, longitude, latitude, scraped_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (id_, price, surface, price_per_m2, arr, rooms, longitude, latitude))
            cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
            cleaned += 1

        conn.commit()
        logger.info(f"Silver: {cleaned} rows cleaned and inserted")

    except Exception as e:
        conn.rollback()
        logger.error(f"bronze_to_silver failed: {e}", exc_info=True)
        raise
    finally:
        cur.close()
        conn.close()


def silver_to_gold():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
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
        cur.execute("""
            INSERT INTO scraper_runs (status, listings_added)
            VALUES ('success', (SELECT COUNT(*) FROM bronze_listings WHERE scraped_at::date = CURRENT_DATE))
        """)
        conn.commit()
        logger.info(f"Gold: daily stats updated for {date.today()}")

    except Exception as e:
        conn.rollback()
        logger.error(f"silver_to_gold failed: {e}", exc_info=True)
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    logger.info(f"Pipeline starting — {date.today()}")
    try:
        download_and_load()
        bronze_to_silver()
        silver_to_gold()
        logger.info("Pipeline complete")
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        try:
            conn = psycopg2.connect(os.environ["DATABASE_URL"])
            cur = conn.cursor()
            cur.execute("INSERT INTO scraper_runs (status, listings_added) VALUES ('failed', 0)")
            conn.commit()
            conn.close()
        except Exception as db_error:
            logger.error(f"Also failed to log failure to DB: {db_error}")
        raise
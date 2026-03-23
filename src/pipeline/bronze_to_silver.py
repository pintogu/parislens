import psycopg2
import os
import re
from dotenv import load_dotenv

load_dotenv()

def parse_price(raw):
    # "830.000 €" → 830000
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None

def parse_surface(raw):
    # "77 m²" or "49,80 m²" → 77.0 or 49.8
    if not raw:
        return None
    match = re.search(r"([\d,\.]+)\s*m", raw)
    if match:
        return float(match.group(1).replace(",", "."))
    return None

def parse_arrondissement(raw):
    # "Paris 1Er (75001)" → "75001"
    # "Paris 13E" → "75013"
    if not raw:
        return None

    # Try to find the 5-digit code directly: (75001)
    match = re.search(r"75(\d{3})", raw)
    if match:
        return "75" + match.group(1)

    # Otherwise parse the roman-style name: Paris 13E → 75013
    match = re.search(r"paris\s+(\d+)", raw, re.IGNORECASE)
    if match:
        num = int(match.group(1))
        return f"75{num:03d}"

    return None

def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    # Get all unprocessed bronze rows
    cur.execute("""
        SELECT id, price_raw, surface_raw, arrondissement
        FROM bronze_listings
        WHERE processed = FALSE
    """)
    rows = cur.fetchall()
    print(f"Processing {len(rows)} bronze rows...")

    cleaned = 0
    skipped = 0

    for row in rows:
        id_, price_raw, surface_raw, arr_raw = row

        price = parse_price(price_raw)
        surface = parse_surface(surface_raw)
        arrondissement = parse_arrondissement(arr_raw)

        # Skip if anything is missing or nonsensical
        if not price or not surface or not arrondissement:
            print(f"  Skipping row {id_} — missing data")
            skipped += 1
            cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
            continue

        if surface == 0:
            skipped += 1
            cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
            continue

        price_per_m2 = round(price / surface, 2)

        # Save to silver
        cur.execute("""
            INSERT INTO silver_listings
              (bronze_id, price_eur, surface_m2, price_per_m2, arrondissement, scraped_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (id_, price, surface, price_per_m2, arrondissement))

        # Mark bronze row as processed
        cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
        cleaned += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Cleaned: {cleaned} rows saved to Silver")
    print(f"⚠️  Skipped: {skipped} rows (missing data)")

if __name__ == "__main__":
    run()

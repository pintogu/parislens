import os
import re
import psycopg2
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

MIN_PRICE, MAX_PRICE = 50_000, 30_000_000
MIN_SURFACE, MAX_SURFACE = 5, 1000

def parse_price(raw):
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None

def parse_surface(raw):
    if not raw:
        return None
    match = re.search(r"([\d,\.]+)\s*m", raw)
    return float(match.group(1).replace(",", ".")) if match else None

def parse_arrondissement(raw):
    if not raw:
        return None
    match = re.search(r"75(\d{3})", raw)
    if match:
        return "75" + match.group(1)
    match = re.search(r"paris\s+(\d+)", raw, re.IGNORECASE)
    return f"75{int(match.group(1)):03d}" if match else None

def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    cur.execute("SELECT id, price_raw, surface_raw, arrondissement FROM bronze_listings WHERE processed = FALSE")
    rows = cur.fetchall()
    logger.info(f"Processing {len(rows)} bronze rows...")

    cleaned, skipped = 0, 0
    try:
        for id_, price_raw, surface_raw, arr_raw in rows:
            price = parse_price(price_raw)
            surface = parse_surface(surface_raw)
            arrondissement = parse_arrondissement(arr_raw)

            skip_reason = None
            if not price or not surface or not arrondissement:
                skip_reason = f"missing data (price={price}, surface={surface}, arr={arrondissement})"
            elif not (MIN_SURFACE < surface < MAX_SURFACE):
                skip_reason = f"surface out of range ({surface} m²)"
            elif not (MIN_PRICE < price < MAX_PRICE):
                skip_reason = f"price out of range (€{price})"

            if skip_reason:
                logger.warning(f"Row {id_} skipped — {skip_reason}")
                cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
                skipped += 1
                continue

            cur.execute("""
                INSERT INTO silver_listings (bronze_id, price_eur, surface_m2, price_per_m2, arrondissement, scraped_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (id_, price, surface, round(price / surface, 2), arrondissement))
            cur.execute("UPDATE bronze_listings SET processed=TRUE WHERE id=%s", (id_,))
            cleaned += 1

        conn.commit()
        logger.info(f"Done — {cleaned} saved to Silver, {skipped} skipped")

    except Exception as e:
        conn.rollback()
        logger.error(f"bronze_to_silver failed: {e}", exc_info=True)
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
import psycopg2
import os
from dotenv import load_dotenv
from datetime import date
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    today = date.today()

    try:
        cur.execute("""
            SELECT
                arrondissement,
                ROUND(AVG(price_per_m2)::numeric, 2) as avg_price,
                COUNT(*) as listing_count
            FROM silver_listings
            WHERE scraped_at::date = CURRENT_DATE
            GROUP BY arrondissement
            ORDER BY arrondissement
        """)
        rows = cur.fetchall()
        logger.info(f"Aggregating {len(rows)} arrondissements for {today}")

        saved = 0
        for arr, avg_price, count in rows:
            cur.execute("""
                INSERT INTO gold_daily_stats
                  (arrondissement, date, avg_price_per_m2, listing_count)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (arrondissement, date) DO UPDATE
                  SET avg_price_per_m2 = EXCLUDED.avg_price_per_m2,
                      listing_count = EXCLUDED.listing_count,
                      computed_at = NOW()
            """, (arr, today, avg_price, count))
            logger.info(f"  {arr} → €{avg_price:,.0f}/m² ({count} listings)")
            saved += 1

        conn.commit()
        logger.info(f"Gold table updated — {saved} arrondissements for {today}")

    except Exception as e:
        conn.rollback()
        logger.error(f"silver_to_gold failed: {e}", exc_info=True)
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run()
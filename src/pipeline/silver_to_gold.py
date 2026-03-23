import psycopg2
import os
from dotenv import load_dotenv
from datetime import date

load_dotenv()

def run():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()

    today = date.today()

    # Get average price per m² per arrondissement from silver
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
    print(f"Aggregating {len(rows)} arrondissements for {today}\n")

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
        print(f"  {arr} → €{avg_price:,.0f}/m² ({count} listings)")
        saved += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ Gold table updated — {saved} arrondissements for {today}")

if __name__ == "__main__":
    run()

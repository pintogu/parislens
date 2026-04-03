import psycopg2
import os
from dotenv import load_dotenv
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)

def create_tables():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bronze_listings (
                id          SERIAL PRIMARY KEY,
                title       TEXT,
                price_raw   TEXT,
                surface_raw TEXT,
                arrondissement TEXT,
                rooms_raw       TEXT,
                longitude_raw   TEXT,
                latitude_raw    TEXT,
                url         TEXT UNIQUE,
                scraped_at  TIMESTAMPTZ DEFAULT NOW(),
                processed   BOOLEAN DEFAULT FALSE
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS silver_listings (
                id             SERIAL PRIMARY KEY,
                bronze_id      INTEGER REFERENCES bronze_listings(id),
                price_eur      INTEGER,
                surface_m2     FLOAT,
                price_per_m2   FLOAT,
                arrondissement TEXT,
                rooms          INTEGER,
                longitude      FLOAT,
                latitude       FLOAT,
                scraped_at     TIMESTAMPTZ
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold_daily_stats (
                id               SERIAL PRIMARY KEY,
                arrondissement   TEXT NOT NULL,
                date             DATE NOT NULL,
                avg_price_per_m2 FLOAT,
                listing_count    INTEGER,
                computed_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (arrondissement, date)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scraper_runs (
                id              SERIAL PRIMARY KEY,
                ran_at          TIMESTAMPTZ DEFAULT NOW(),
                status          TEXT,
                listings_added  INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS model_runs (
                id              SERIAL PRIMARY KEY,
                ran_at          TIMESTAMPTZ DEFAULT NOW(),
                status          TEXT DEFAULT 'running',
                model_path      TEXT,
                cv_rmse         FLOAT,
                train_rmse      FLOAT,
                train_mae       FLOAT,
                train_r2        FLOAT,
                rows_used       INTEGER
            );
        """)
        conn.commit()
        logger.info("All tables created successfully")

    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create tables: {e}", exc_info=True)
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    create_tables()
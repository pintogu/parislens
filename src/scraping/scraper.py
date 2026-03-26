# NOTE: This scraper was the original data collection approach, targeting PAP.fr.
# It was abandoned because PAP.fr and SeLoger use Cloudflare bot protection,
# which blocks automated browser access even with Playwright and realistic headers.
# The pipeline now uses the official DVF dataset from data.gouv.fr instead.
# This file is kept for reference but is NOT part of the active pipeline.

import asyncio
import os
import random

import psycopg2
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from logger import get_logger

load_dotenv()
logger = get_logger(__name__)


ARRONDISSEMENT_URLS = {
    "75001": "https://www.pap.fr/annonce/vente-appartements-paris-1er-75001-g37680",
    "75002": "https://www.pap.fr/annonce/vente-appartements-paris-2e-75002-g37681",
    "75003": "https://www.pap.fr/annonce/vente-appartements-paris-3e-75003-g37682",
    "75004": "https://www.pap.fr/annonce/vente-appartements-paris-4e-75004-g37683",
    "75005": "https://www.pap.fr/annonce/vente-appartements-paris-5e-75005-g37684",
    "75006": "https://www.pap.fr/annonce/vente-appartements-paris-6e-75006-g37685",
    "75007": "https://www.pap.fr/annonce/vente-appartements-paris-7e-75007-g37686",
    "75008": "https://www.pap.fr/annonce/vente-appartements-paris-8e-75008-g37687",
    "75009": "https://www.pap.fr/annonce/vente-appartements-paris-9e-75009-g37688",
    "75010": "https://www.pap.fr/annonce/vente-appartements-paris-10e-75010-g37689",
    "75011": "https://www.pap.fr/annonce/vente-appartements-paris-11e-75011-g37690",
    "75012": "https://www.pap.fr/annonce/vente-appartements-paris-12e-75012-g37691",
    "75013": "https://www.pap.fr/annonce/vente-appartements-paris-13e-75013-g37692",
    "75014": "https://www.pap.fr/annonce/vente-appartements-paris-14e-75014-g37693",
    "75015": "https://www.pap.fr/annonce/vente-appartements-paris-15e-75015-g37694",
    "75016": "https://www.pap.fr/annonce/vente-appartements-paris-16e-75016-g37695",
    "75017": "https://www.pap.fr/annonce/vente-appartements-paris-17e-75017-g37696",
    "75018": "https://www.pap.fr/annonce/vente-appartements-paris-18e-75018-g37697",
    "75019": "https://www.pap.fr/annonce/vente-appartements-paris-19e-75019-g37698",
    "75020": "https://www.pap.fr/annonce/vente-appartements-paris-20e-75020-g37699",
}


def save_to_bronze(cur, listings):
    saved = 0
    for l in listings:
        cur.execute(
            """
            INSERT INTO bronze_listings (location_raw, price_raw, surface_raw, arrondissement, url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (l["location_raw"], l["price_raw"], l["surface_raw"], l["arrondissement"], l["url"]),
        )
        if cur.rowcount > 0:
            saved += 1
    return saved


async def scrape_arrondissement(page, arrondissement, url, cookie_dismissed):
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        logger.warning(f"Failed to load {arrondissement}: {e} — skipping")
        return [], cookie_dismissed

    await page.wait_for_timeout(3000)

    if not cookie_dismissed:
        try:
            await page.click("text=Continuer sans accepter", timeout=5000)
            await page.wait_for_timeout(2000)
            cookie_dismissed = True
        except Exception:
            pass

    html = await page.content()
    if "verify you are human" in html.lower() or "cloudflare" in html.lower():
        logger.warning(f"Blocked on {arrondissement} — skipping")
        return [], cookie_dismissed

    # scroll to trigger lazy loading
    await page.evaluate("window.scrollTo(0, 600)")
    await page.wait_for_timeout(1000)
    await page.evaluate("window.scrollTo(0, 1200)")
    await page.wait_for_timeout(1000)

    cards = await page.query_selector_all(".item-body")
    listings = []

    for card in cards:
        link_el = await card.query_selector("a.item-title")
        if not link_el:
            continue

        href = await link_el.get_attribute("href")
        if not href or "/annonces/" not in href:
            continue

        price_el = await card.query_selector(".item-price")
        price_raw = (await price_el.inner_text()).strip() if price_el else None
        if not price_raw:
            continue

        location_el = await card.query_selector(".h1")
        location_raw = (await location_el.inner_text()).strip() if location_el else arrondissement

        surface_raw = None
        for tag in await card.query_selector_all(".item-tags li"):
            text = await tag.inner_text()
            if "m²" in text:
                surface_raw = text.strip()
                break

        listings.append({
            "location_raw": location_raw,
            "price_raw": price_raw,
            "surface_raw": surface_raw,
            "arrondissement": arrondissement,
            "url": "https://www.pap.fr" + href,
        })

    return listings, cookie_dismissed


async def main():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    total_saved = 0
    cookie_dismissed = False

    async with async_playwright() as p:
        # headless=True needed for Docker — no display available
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        for arrondissement, url in ARRONDISSEMENT_URLS.items():
            logger.info(f"Scraping {arrondissement}...")
            listings, cookie_dismissed = await scrape_arrondissement(page, arrondissement, url, cookie_dismissed)

            if listings:
                saved = save_to_bronze(cur, listings)
                conn.commit()
                total_saved += saved
                logger.info(f"  {len(listings)} found, {saved} new saved")
            else:
                logger.info(f"  nothing found for {arrondissement}")

            await page.wait_for_timeout(random.randint(3000, 6000))

        await browser.close()

    cur.close()
    conn.close()
    logger.info(f"Done — {total_saved} new listings saved to Bronze")


if __name__ == "__main__":
    asyncio.run(main())
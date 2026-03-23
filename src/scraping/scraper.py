import asyncio
import psycopg2
import os
import random
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# One URL per arrondissement — 20 searches, no pagination needed
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

def save_to_bronze(listings):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    cur = conn.cursor()
    saved = 0
    for l in listings:
        try:
            cur.execute("""
                INSERT INTO bronze_listings
                  (title, price_raw, surface_raw, arrondissement, url)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (url) DO NOTHING
            """, (l["title"], l["price_raw"], l["surface_raw"],
                  l["arrondissement"], l["url"]))
            if cur.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f"Error saving: {e}")
    conn.commit()
    cur.close()
    conn.close()
    return saved

async def scrape_arrondissement(page, arrondissement, url, cookie_dismissed):
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    # Dismiss cookie popup only once
    if not cookie_dismissed:
        try:
            await page.click("text=Continuer sans accepter", timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass

    # Check for Cloudflare
    html = await page.content()
    if "verify you are human" in html.lower() or "cloudflare" in html.lower():
        print(f"  ⚠️  Blocked on {arrondissement} — skipping")
        return [], cookie_dismissed

    # Scroll to trigger lazy loading
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
        if "/annonces/" not in href:
            continue

        price_el = await card.query_selector(".item-price")
        price_raw = (await price_el.inner_text()).strip() if price_el else None
        if not price_raw:
            continue

        arr_el = await card.query_selector(".h1")
        arr_raw = (await arr_el.inner_text()).strip() if arr_el else arrondissement

        tags = await card.query_selector_all(".item-tags li")
        surface_raw = None
        for tag in tags:
            text = await tag.inner_text()
            if "m²" in text:
                surface_raw = text.strip()

        listings.append({
            "title": arr_raw,
            "price_raw": price_raw,
            "surface_raw": surface_raw,
            "arrondissement": arrondissement,  # use the known arrondissement code
            "url": "https://www.pap.fr" + href,
        })

    return listings, True

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        total_saved = 0
        cookie_dismissed = False

        for arrondissement, url in ARRONDISSEMENT_URLS.items():
            print(f"Scraping {arrondissement}...")
            listings, cookie_dismissed = await scrape_arrondissement(
                page, arrondissement, url, cookie_dismissed
            )
            if listings:
                saved = save_to_bronze(listings)
                total_saved += saved
                print(f"  ✅ {len(listings)} listings, {saved} new saved")
            
            # Random pause between arrondissements
            wait = random.randint(3000, 6000)
            await page.wait_for_timeout(wait)

        print(f"\n🎉 Done — {total_saved} new listings saved to Bronze")
        await browser.close()

asyncio.run(main())

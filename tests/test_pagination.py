import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto(
            "https://www.pap.fr/annonce/vente-appartements-paris-75-g439",
            wait_until="networkidle"
        )
        await page.click("text=Continuer sans accepter")
        await page.wait_for_timeout(2000)

        # Get the HTML around the pagination
        html = await page.content()
        idx = html.find("Suivante")
        if idx > 0:
            print(html[idx-800:idx+200])

        input("Press Enter to close...")
        await browser.close()

asyncio.run(main())

import asyncio
import json
from datetime import datetime

import httpx
from playwright.async_api import async_playwright

DISCORD_WEBHOOK = "SETT_INN_WEBHOOK_HER"
CHECK_INTERVAL = 45          # sekunder mellom hver sjekk
HEARTBEAT_INTERVAL = 3600    # send "bot lever"-ping til Discord hver time

PRODUCT_URLS = [
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-booster-bundle-me02-5-0196214131613",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-ex-box-2-me02-5-0196214131972",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-prem-poster-coll-me02-5-2-0196214131033",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-deluxe-pin-coll-me02-5-0196214131026",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-mini-tin-me02-5-5-0196214132658"
]
SELECTED_STORES = [
    "Bergen Storsenter",
    "Bergen Xhibition",
    "Bergen Lagunen"
]
STATE_FILE = "norli_state.json"


def normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


async def discord_post(payload: dict) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(DISCORD_WEBHOOK, json=payload)


async def send_startup():
    await discord_post({
        "embeds": [{
            "title": "🟢 Norli restock-bot er oppe",
            "description": f"Overvåker **{len(PRODUCT_URLS)} produkter** for butikkene:\n" +
                           "\n".join(f"- {s}" for s in SELECTED_STORES),
            "color": 0x6daa45,
            "fields": [
                {"name": "Sjekkintervall", "value": f"{CHECK_INTERVAL}s", "inline": True},
                {"name": "Heartbeat", "value": f"Hver {HEARTBEAT_INTERVAL // 60} min", "inline": True},
            ],
            "footer": {"text": f"Startet {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}
        }]
    })


async def send_heartbeat(checks: int, restocks: int):
    await discord_post({
        "embeds": [{
            "title": "💓 Bot er fortsatt aktiv",
            "color": 0x4F98A3,
            "fields": [
                {"name": "Sjekker utført", "value": str(checks), "inline": True},
                {"name": "Restock-varsler sendt", "value": str(restocks), "inline": True},
                {"name": "Tid", "value": datetime.now().strftime("%H:%M:%S"), "inline": True},
            ],
            "footer": {"text": f"Neste heartbeat om {HEARTBEAT_INTERVAL // 60} min"}
        }]
    })


async def send_restock(product: dict, stores: list[str]):
    store_text = "\n".join(f"- {store}" for store in stores) if stores else "Fant ikke butikknavn, men produktet ser tilgjengelig ut"
    embed = {
        "title": f"🎴 RESTOCK: {product['title']}",
        "url": product["url"],
        "description": store_text,
        "color": 0xFFCC00,
        "fields": [
            {"name": "Valgte butikker", "value": ", ".join(SELECTED_STORES) or "Ingen filter", "inline": False},
            {"name": "Tid", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True}
        ]
    }
    if product.get("image"):
        embed["thumbnail"] = {"url": product["image"]}
    await discord_post({"content": "@here", "embeds": [embed]})


async def extract_store_hits(page) -> list[str]:
    texts = []
    selectors = ["body", "[class*='store']", "[class*='Store']", "[class*='pickup']", "[class*='Pickup']", "[class*='collect']"]
    for selector in selectors:
        for node in await page.query_selector_all(selector):
            try:
                text = await node.inner_text()
                if text:
                    texts.append(text)
            except Exception:
                pass
    body_norm = normalize("\n".join(texts))
    return sorted({store for store in SELECTED_STORES if normalize(store) in body_norm})


async def inspect_product(page, url: str) -> dict | None:
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(2000)
    title = await page.title()
    body_text = normalize(await page.locator("body").inner_text())

    if "utsolgt" in body_text and "klikk og hent" not in body_text:
        return None

    image = ""
    meta = page.locator('meta[property="og:image"]')
    if await meta.count():
        image = await meta.get_attribute('content') or ""

    store_hits = await extract_store_hits(page)
    in_store_signal = any(signal in body_text for signal in [
        "klikk og hent", "hent i butikk", "reserver i butikk", "tilgjengelig i butikk"
    ])

    if SELECTED_STORES and not store_hits:
        return None
    if not in_store_signal and not store_hits:
        return None

    return {"url": url, "title": title.replace(" - Norli Bokhandel", "").strip(), "image": image, "stores": store_hits}


async def run_loop():
    if DISCORD_WEBHOOK == "SETT_INN_WEBHOOK_HER":
        raise SystemExit("Sett inn Discord webhook før du starter boten.")

    await send_startup()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Bot startet. Overvåker {len(PRODUCT_URLS)} produkter.")

    state = load_state()
    checks = 0
    restocks = 0
    last_heartbeat = asyncio.get_event_loop().time()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = await context.new_page()

        while True:
            checks += 1
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Sjekk #{checks} – {len(PRODUCT_URLS)} produkter...")

            for url in PRODUCT_URLS:
                try:
                    product = await inspect_product(page, url)
                    was_live = state.get(url, False)
                    is_live = bool(product)
                    if is_live and not was_live:
                        restocks += 1
                        await send_restock(product, product["stores"])
                        print(f"  🎴 RESTOCK: {product['title']} – {product['stores']}")
                    state[url] = is_live
                except Exception as exc:
                    print(f"  ❌ Feil på {url}: {exc}")

            save_state(state)

            now = asyncio.get_event_loop().time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                await send_heartbeat(checks, restocks)
                last_heartbeat = now
                print(f"  💓 Heartbeat sendt til Discord")

            await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())

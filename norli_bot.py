import asyncio
import json
import os
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "SETT_INN_WEBHOOK_HER")
CHECK_INTERVAL = 60
HEARTBEAT_INTERVAL = 3600

PRODUCT_URLS = [
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-booster-bundle-me02-5-0196214131613",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-ex-box-2-me02-5-0196214131972",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-prem-poster-coll-me02-5-2-0196214131033",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-deluxe-pin-coll-me02-5-0196214131026",
    "https://www.norli.no/leker/kreative-leker/samlekort/pokemonkort/pokemon-mini-tin-me02-5-5-0196214132658",
]

# Telemark og Vestfold butikker
SELECTED_STORES = [
    # Telemark
    "Norli Akademisk Notodden",
    "Norli Akademisk Porsgrunn",
    "Norli Arkaden Skien",
    "Norli Bøsenteret",
    "Norli Herkules, Skien",
    "Norli Ringo Alti Brotorvet, Stathelle",
    "Norli Seljord",
    "Norli Tuven Senter, Notodden",
    # Vestfold
    "Norli Akademisk Vestfold",
    "Norli Amfi Larvik",
    "Norli Bellevue Senteret, Teie",
    "Norli Farmandstredet, Tønsberg",
    "Norli Hvaltorget, Sandefjord",
    "Norli Leketorget Holmestrand",
    "Norli Revetal",
    "Norli Ringo Vektergården, Horten",
    "Norli Stokke Senter",
    "Norli Storgata, Sandefjord",
    "Norli Tolvsrød, Tønsberg",
]

STATE_FILE = "norli_state.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "nb-NO,nb;q=0.9",
}


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
    store_list = "\n".join(f"- {s}" for s in SELECTED_STORES)
    await discord_post({
        "embeds": [{
            "title": "🟢 Norli restock-bot er oppe",
            "description": f"Overvåker **{len(PRODUCT_URLS)} produkter** for **{len(SELECTED_STORES)} butikker** i Telemark og Vestfold:\n{store_list}",
            "color": 0x6DAA45,
            "fields": [
                {"name": "Sjekkintervall", "value": f"{CHECK_INTERVAL}s", "inline": True},
                {"name": "Heartbeat", "value": f"Hver {HEARTBEAT_INTERVAL // 60} min", "inline": True},
            ],
            "footer": {"text": f"Startet {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"},
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
            "footer": {"text": f"Neste heartbeat om {HEARTBEAT_INTERVAL // 60} min"},
        }]
    })


async def send_restock(product: dict, stores: list):
    store_text = (
        "\n".join(f"- {s}" for s in stores)
        if stores
        else "Fant ikke butikknavn, men produktet ser tilgjengelig ut"
    )
    embed = {
        "title": f"🎴 RESTOCK: {product['title']}",
        "url": product["url"],
        "description": store_text,
        "color": 0xFFCC00,
        "fields": [
            {"name": "Tid", "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "inline": True},
        ],
    }
    if product.get("image"):
        embed["thumbnail"] = {"url": product["image"]}
    await discord_post({"content": "@here", "embeds": [embed]})


async def fetch_page(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
    except Exception as e:
        print(f"  Fetch-feil {url}: {e}")
        return None


async def inspect_product(url: str) -> dict | None:
    html = await fetch_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    body_text = normalize(soup.get_text(" ", strip=True))

    if "utsolgt" in body_text and "klikk og hent" not in body_text:
        return None

    in_store_signal = any(signal in body_text for signal in [
        "klikk og hent", "hent i butikk", "reserver i butikk", "tilgjengelig i butikk"
    ])

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "").replace(" - Norli Bokhandel", "").strip()
    if not title:
        tag = soup.find("h1")
        title = tag.get_text(strip=True) if tag else url

    image = ""
    og_image = soup.find("meta", property="og:image")
    if og_image:
        image = og_image.get("content", "")

    store_hits = sorted({
        store for store in SELECTED_STORES
        if normalize(store) in body_text
    })

    if SELECTED_STORES and not store_hits:
        return None
    if not in_store_signal and not store_hits:
        return None

    return {"url": url, "title": title, "image": image, "stores": store_hits}


async def run_loop():
    await send_startup()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Bot startet. Overvåker {len(PRODUCT_URLS)} produkter, {len(SELECTED_STORES)} butikker.")

    state = load_state()
    checks = 0
    restocks = 0
    last_heartbeat = asyncio.get_event_loop().time()

    while True:
        checks += 1
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sjekk #{checks} – {len(PRODUCT_URLS)} produkter...")

        for url in PRODUCT_URLS:
            try:
                product = await inspect_product(url)
                was_live = state.get(url, False)
                is_live = bool(product)
                if is_live and not was_live:
                    restocks += 1
                    await send_restock(product, product["stores"])
                    print(f"  RESTOCK: {product['title']} – {product['stores']}")
                state[url] = is_live
            except Exception as exc:
                print(f"  Feil på {url}: {exc}")

        save_state(state)

        now = asyncio.get_event_loop().time()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL:
            await send_heartbeat(checks, restocks)
            last_heartbeat = now
            print("  Heartbeat sendt til Discord")

        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_loop())

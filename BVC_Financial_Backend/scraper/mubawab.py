"""
Mubawab.ma scraper — supplementary real estate listings
"""

import re
import asyncio
import random
import hashlib
from datetime import datetime
from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.mubawab.ma"

CITY_SLUGS = {
    "Casablanca": "casablanca",
    "Rabat": "rabat",
    "Marrakech": "marrakech",
    "Fès": "fes",
    "Tanger": "tanger",
    "Agadir": "agadir",
    "Meknès": "meknes",
    "Oujda": "oujda",
    "Tétouan": "tetouan",
    "El Jadida": "el-jadida",
    "Kenitra": "kenitra",
    "Settat": "settat",
}

MODES = [
    ("Vente", "immobilier-a-vendre"),
    ("Location", "immobilier-a-louer"),
]

HEADERS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-MA,fr;q=0.9",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
    },
]


def _make_id(url: str) -> str:
    return "MB-" + hashlib.md5(url.encode()).hexdigest()[:10].upper()  # type: ignore


def _parse_price(text: str) -> int:
    """Extract price ONLY if DH or MAD marker is present."""
    clean_text = text.replace("\xa0", "").replace(" ", "").replace("\u202f", "").upper()
    if "DH" not in clean_text and "MAD" not in clean_text:
        return 0
    
    m = re.search(r"(\d+(?:[\.,]\d+)?)", clean_text.replace(",", ""))
    if m:
        # Handle decimal removal if it's just formatting
        val_str = m.group(1).replace(".", "").replace(",", "")
        return int(val_str)
    return 0


def _parse_surface(text: str) -> float:
    """Extract surface ONLY if m² marker is present."""
    clean_text = text.lower()
    if "m²" not in clean_text and "m2" not in clean_text:
        return 0.0
    
    m = re.search(r"([\d\.,]+)\s*m", clean_text.replace(",", "."))
    return float(m.group(1)) if m else 0.0


def _parse_rooms(text: str) -> int:
    m = re.search(r"(\d+)\s*(chambre|pièce|ch\.)", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _parse_type(text: str) -> str:
    mapping = {
        "appartement": "Appartement", "villa": "Villa", "studio": "Studio",
        "riad": "Riad", "bureau": "Bureau", "local": "Local commercial",
        "terrain": "Terrain", "maison": "Maison", "duplex": "Duplex",
    }
    low = text.lower()
    for key, val in mapping.items():
        if key in low:
            return val
    return "Appartement"


def _parse_date(text: str) -> str:
    """Parse Mubawab dates like 'Il y a 2 jours' or '12/03/2026'"""
    low = text.lower()
    now = datetime.now()
    if "hier" in low:
        from datetime import timedelta
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    elif "il y a" in low:
        m = re.search(r"(\d+)", low)
        if m:
            from datetime import timedelta
            return (now - timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
    
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return now.strftime("%Y-%m-%d")


def _parse_cards(html: str, city: str, transaction: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    now = datetime.utcnow().isoformat()

    cards = (
        soup.select("li.listingBox") or
        soup.select("div.listingBox") or
        soup.select("[class*='listing']") or
        []
    )

    if not cards:
        cards = soup.select("a[href*='/fr/annonce/']")

    for card in cards:
        try:
            link = card.find("a", href=True) if card.name != "a" else card
            if not link:
                continue
            href = link.get("href", "")
            if not href:
                continue
            url = href if href.startswith("http") else BASE + href

            full_text = card.get_text(" ", strip=True)

            # Title
            title_el = card.find(["h2", "h3", "a"], class_=re.compile(r"title|Title|listing", re.I))
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                title = full_text[:80]

            # Price
            price_el = card.find(["span", "div"], class_=re.compile(r"price|Price|prix", re.I))
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            if not price_text:
                m = re.search(r"[\d\s]+(?:DH|MAD)", full_text)
                price_text = m.group(0) if m else "0"
            price = _parse_price(price_text)

            if price == 0:
                continue

            surface = _parse_surface(full_text)
            if surface == 0:
                # Surface area is highly unreliable if markers are missing on Mubawab
                continue
                
            rooms = _parse_rooms(full_text)
            prop_type = _parse_type(url + " " + full_text)

            # Neighborhood from card location text
            loc_el = card.find(["span", "div", "p"], class_=re.compile(r"location|Location|address|area", re.I))
            loc_text = loc_el.get_text(strip=True) if loc_el else ""
            # Try to extract neighborhood part after comma
            m = re.search(r",\s*(.+)", loc_text)
            neighborhood = m.group(1).strip()[:50] if m else "Centre"  # type: ignore

            ppsm = int(price / surface) if surface > 0 and price > 0 else 0

            results.append({
                "id": _make_id(url),
                "title": title[:200],
                "type": prop_type,
                "transaction": transaction,
                "city": city,
                "neighborhood": neighborhood,
                "surface": round(surface, 1),  # type: ignore
                "rooms": rooms,
                "price": price,
                "price_per_sqm": ppsm,
                "source": "Mubawab.ma",
                "seller": "Agence",
                "url": url,
                "status": "Vendu" if "vendu" in full_text.lower() else "Actif",
                "date_listing": _parse_date(full_text),
                "date_transaction": None,
                "date_sold": now[:10] if "vendu" in full_text.lower() else None,
                "scraped_at": now,
            })
        except Exception:
            continue

    return results


async def scrape_mubawab(
    log_queue: asyncio.Queue,
    pages_per_combo: int = 20,
) -> AsyncIterator[dict]:
    async def log(level: str, msg: str):
        await log_queue.put({"level": level, "msg": msg})

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for city_name, city_slug in CITY_SLUGS.items():
            for txn_label, mode_slug in MODES:
                city_total = 0
                for page in range(1, pages_per_combo + 1):
                    url = f"{BASE}/fr/ct/{city_slug}/{mode_slug}:p:{page}"
                    try:
                        headers = random.choice(HEADERS)
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 429:
                            await log("WARN", f"[Mubawab] Rate limit on {city_name} p{page} — sleeping 5s")
                            await asyncio.sleep(5)
                            continue
                        if resp.status_code != 200:
                            break

                        listings = _parse_cards(resp.text, city_name, txn_label)
                        if not listings:
                            break

                        for l in listings:
                            yield l

                        city_total += len(listings)  # type: ignore
                        await log("DATA", f"[Mubawab.ma] {city_name} · {txn_label} · p{page} → {len(listings)} listings")

                    except Exception as e:
                        await log("WARN", f"[Mubawab] Error {city_name} p{page}: {e}")
                        break

                    await asyncio.sleep(random.uniform(0.8, 1.6))

                if city_total:
                    await log("SUCCESS", f"[Mubawab.ma] {city_name} {txn_label} — {city_total} listings")

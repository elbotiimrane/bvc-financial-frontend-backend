"""
Sarouty.ma scraper
Targets: https://www.sarouty.ma/en/search?c={city_id}&t={txn_id}&page={page}
"""

import re
import asyncio
import random
import hashlib
from datetime import datetime
from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.sarouty.ma"

# Sarouty requires numeric IDs for cities in their search query
CITY_PARAMS = {
    "Casablanca": 1,
    "Marrakech": 2,
    "Rabat": 3,
    "Tanger": 4,
    "Agadir": 5,
    "Fès": 7,
    "Meknès": 8,
    "Kenitra": 9,
    "Oujda": 11,
    "Tétouan": 14,
    "El Jadida": 15,
    "Settat": 16,
}

# Transaction type IDs
MODES = [
    ("Vente", 1),       # t=1 is Buy
    ("Location", 2),    # t=2 is Rent
]

HEADERS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-MA,fr;q=0.9,en;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    },
]


def _make_id(url: str) -> str:
    return "SR-" + hashlib.md5(url.encode()).hexdigest()[:10].upper()


def _parse_price(text: str) -> int:
    """Extract price ONLY if MAD or DH marker is present."""
    text = text.upper()
    if "MAD" not in text and "DH" not in text:
        return 0
    
    # Remove separators and handle numeric extraction
    clean = text.replace("MAD", "").replace("DH", "").replace(",", "").replace(" ", "").strip()
    m = re.search(r"(\d+)", clean)
    return int(m.group(1)) if m else 0


def _parse_surface(text: str) -> float:
    """Extract surface ONLY if area markers are present."""
    low = text.lower()
    if not any(x in low for x in ["sqm", "sqft", "m²", "m2", "sqv"]):
        return 0.0
    
    m = re.search(r"([\d\.,]+)\s*(?:sq|m)", low.replace(",", ""))
    return float(m.group(1)) if m else 0.0


def _parse_rooms(text: str) -> int:
    m = re.search(r"(\d+)\s*Bed", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _parse_type(url: str, text: str) -> str:
    mapping = {
        "apartment": "Appartement",
        "villa": "Villa",
        "studio": "Studio",
        "riad": "Riad",
        "office": "Bureau",
        "commercial": "Local commercial",
        "land": "Terrain",
        "house": "Maison",
        "duplex": "Duplex"
    }
    low = (url + " " + text).lower()
    for key, val in mapping.items():
        if key in low:
            return val
    return "Appartement"


def _parse_date(text: str) -> str:
    """Parse Sarouty dates like 'Listed on: 12 Mar 2026'"""
    low = text.lower()
    now = datetime.now()
    m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", low)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        year = int(m.group(3))
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        for k, v in months.items():
            if month_str.startswith(k):
                try:
                    return datetime(year, v, day).strftime("%Y-%m-%d")
                except ValueError:
                    break
    return now.strftime("%Y-%m-%d")


def _parse_cards(html: str, city: str, transaction: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    now = datetime.utcnow().isoformat()

    # Find the main listing cards
    cards = soup.select("li[role='article'], div[role='article'], .card, [class*='property-card']")

    # Fallback to links if classes change
    if not cards:
        cards = soup.select("a[href*='/en/property/']")

    for card in cards:
        try:
            link = card.find("a", href=True) if card.name != "a" else card
            if not link:
                continue
            href = link.get("href", "")
            if not href or "/en/property/" not in href:
                continue
            url = href if href.startswith("http") else BASE + href

            full_text = card.get_text(" ", strip=True)

            # Title extraction - usually in h2
            title_el = card.find(["h2", "h3", "p"], class_=re.compile(r"title|heading", re.I))
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                # Pick the first chunk of text that isn't the price
                if "MAD" in full_text:
                    parts = full_text.split("MAD")
                    title = parts[1][:80].strip() if len(parts) > 1 else full_text[:80]
                else:
                    title = full_text[:80]

            # Price extraction
            price_el = card.find(["span", "div"], class_=re.compile(r"price", re.I))
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            if not price_text:
                m = re.search(r"[\d\,]+\s*MAD", full_text)
                price_text = m.group(0) if m else "0"
            price = _parse_price(price_text)

            if price == 0:
                continue

            # Extracted details
            surface = _parse_surface(full_text)
            if surface == 0:
                # Surface area is crucial for Sarouty categorization
                continue
                
            rooms = _parse_rooms(full_text)
            prop_type = _parse_type(url, full_text)

            # Location usually formatted as "Neighborhood, City"
            loc_el = card.find(["span", "div", "p"], class_=re.compile(r"location|address", re.I))
            loc_text = loc_el.get_text(strip=True) if loc_el else ""
            parts = [p.strip() for p in loc_text.split(",")]
            neighborhood = parts[0] if parts and parts[0] != city else "Centre"

            ppsm = int(price / surface) if surface > 0 and price > 0 else 0

            # Find agency name (usually in an alt tag of a logo or specific text)
            agency_el = card.find("img", alt=re.compile(r"Broker|Agency|Agent", re.I))
            seller = agency_el.get("alt", "Agence").replace("Broker Logo", "").strip() if agency_el else "Agence"

            results.append({
                "id": _make_id(url),
                "title": title[:200],
                "type": prop_type,
                "transaction": transaction,
                "city": city,
                "neighborhood": neighborhood[:50],
                "surface": round(surface, 1),
                "rooms": rooms,
                "price": price,
                "price_per_sqm": ppsm,
                "source": "Sarouty.ma",
                "seller": seller[:80] if seller else "Agence",
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


async def scrape_sarouty(
    log_queue: asyncio.Queue,
    pages_per_combo: int = 20,
) -> AsyncIterator[dict]:
    
    async def log(level: str, msg: str):
        await log_queue.put({"level": level, "msg": msg})

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for city_name, city_id in CITY_PARAMS.items():
            for txn_label, txn_id in MODES:
                city_total = 0
                for page in range(1, pages_per_combo + 1):
                    # Search endpoint logic using query parameters
                    url = f"{BASE}/en/search?c={city_id}&t={txn_id}&page={page}"
                    try:
                        headers = random.choice(HEADERS)
                        resp = await client.get(url, headers=headers)
                        
                        if resp.status_code == 429:
                            await log("WARN", f"[Sarouty] Rate limit on {city_name} p{page} — sleeping 5s")
                            await asyncio.sleep(5)
                            continue
                            
                        if resp.status_code != 200:
                            break

                        listings = _parse_cards(resp.text, city_name, txn_label)
                        
                        if not listings:
                            break

                        for l in listings:
                            yield l

                        city_total += len(listings)
                        await log("DATA", f"[Sarouty.ma] {city_name} · {txn_label} · p{page} → {len(listings)} listings")

                    except Exception as e:
                        await log("WARN", f"[Sarouty] Error {city_name} p{page}: {e}")
                        break

                    await asyncio.sleep(random.uniform(0.8, 2.0))

                if city_total:
                    await log("SUCCESS", f"[Sarouty.ma] {city_name} {txn_label} complete — {city_total} listings")

"""
Avito.ma scraper — real estate listings
Targets: https://www.avito.ma/fr/{city}/immobilier--{mode}?o={page}

Listing cards on Avito.ma use consistent structure:
  - Each ad is an <article> or <li> with class containing 'sc-1nre5ec'
  - Title in <h3> or <p class="sc-kfPuZi">
  - Price in span with class containing 'sc-gEvEer'
  - Details (surface, rooms) in <span> elements inside the card
"""

import re
import asyncio
import random
import hashlib
from datetime import datetime
from typing import AsyncIterator

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.avito.ma"

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
    "El Jadida": "el_jadida",
    "Kenitra": "kenitra",
    "Settat": "settat",
}

MODES = [
    ("Vente", "immobilier--%C3%A0_vendre"),
    ("Location", "immobilier--%C3%A0_louer"),
]

HEADERS = [
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-MA,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,image/webp,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xhtml+xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    },
]


def _make_id(url: str) -> str:
    return "AV-" + hashlib.md5(url.encode()).hexdigest()[:10].upper()


def _parse_price(text: str) -> int:
    """Extract integer price ONLY if currency marker (DH/MAD) is present."""
    clean_text = text.replace("\xa0", " ").replace(" ", "").replace("\u202f", "").upper()
    if "DH" not in clean_text and "MAD" not in clean_text:
        return 0

    # Look for digits followed by (or preceded by) currency markers
    m = re.search(r"(\d+(?:[\.,]\d+)?)", clean_text.replace(",", ""))
    if m:
        val_str = m.group(1).replace(",", "")
        val = float(val_str)
        # Handle 'millions' abbreviation
        if "MILLION" in clean_text:
            val *= 1_000_000
        return int(val)
    return 0


def _parse_surface(text: str) -> float:
    """Extract surface ONLY if area marker (m², m2, sqm) is present."""
    clean_text = text.replace("\xa0", " ").replace(" ", "").replace("\u202f", "").lower()
    if not re.search(r"m²|m2|sqm|surface", clean_text):
        return 0.0
    
    m = re.search(r"([\d\.,]+)\s*(?:m|sq)", clean_text.replace(",", "."))
    return float(m.group(1)) if m else 0.0


def _parse_rooms(text: str) -> int:
    m = re.search(r"(\d+)\s*chambre", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def _extract_neighborhood(detail_text: str, city: str) -> str:
    """Extract neighborhood from 'Appartements dans Casablanca, Maarif'"""
    m = re.search(r"dans\s+[^,]+,\s*(.+)", detail_text, re.IGNORECASE)
    if m:
        hood = m.group(1).strip()
        # Remove trailing junk
        hood = re.sub(r"\s+\d+.*$", "", hood).strip()
        if hood and hood.lower() not in ("toute la ville", "autre secteur", city.lower()):
            return hood
    return "Centre"


def _parse_type(category_text: str) -> str:
    mapping = {
        "appartement": "Appartement",
        "villa": "Villa",
        "studio": "Studio",
        "riad": "Riad",
        "bureau": "Bureau",
        "local": "Local commercial",
        "terrain": "Terrain",
        "ferme": "Terrain",
        "maison": "Maison",
        "duplex": "Duplex",
    }
    low = category_text.lower()
    for key, val in mapping.items():
        if key in low:
            return val
    return "Appartement"


def _parse_date(text: str) -> str:
    """Parse Avito's date strings (e.g. 'aujourd'hui, 14:20', 'hier', '12 mars')"""
    low = text.lower()
    now = datetime.now()
    
    if "aujourd" in low:
        return now.strftime("%Y-%m-%d")
    elif "hier" in low:
        from datetime import timedelta
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Absolute dates like '12 Mars'
    m = re.search(r"(\d+)\s+([a-zéû]+)", low)
    if m:
        day = int(m.group(1))
        month_str = m.group(2)
        months = {
            "jan": 1, "fév": 2, "mar": 3, "avr": 4, "mai": 5, "juin": 6,
            "juil": 7, "aoû": 8, "sep": 9, "oct": 10, "nov": 11, "déc": 12
        }
        for k, v in months.items():
            if month_str.startswith(k):
                try:
                    return datetime(now.year, v, day).strftime("%Y-%m-%d")
                except ValueError:
                    break
    return now.strftime("%Y-%m-%d")


def _parse_cards(html: str, city: str, transaction: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []
    now = datetime.utcnow().isoformat()

    # Avito uses article tags or li items for listing cards
    # Try multiple selectors for robustness
    cards = (
        soup.select("article[data-testid='ad']") or
        soup.select("li[data-testid='ad-card']") or
        soup.select("article.sc-1nre5ec-0") or
        soup.select("[class*='sc-1nre5ec']") or
        []
    )

    # Fallback: find all anchors that look like listing URLs
    if not cards:
        cards = soup.select("a[href*='/fr/'][href$='.htm']")

    for card in cards:
        try:
            # Get URL
            link = card.find("a", href=True) if card.name != "a" else card
            if not link:
                continue
            href = link.get("href", "")
            if not href or ".htm" not in href:
                continue
            url = href if href.startswith("http") else BASE + href

            # Skip promoted/immo-neuf links
            if "immoneuf.avito" in url or "utm_" in url:
                continue

            full_text = card.get_text(" ", strip=True)

            # Title
            title_el = card.find(["h3", "h2", "p"], class_=re.compile(r"sc-kfPuZi|Title|title", re.I))
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                # Fallback: first significant text
                title = full_text[:80].split("  ")[0].strip()

            # Price
            price_el = card.find(["span", "p"], class_=re.compile(r"sc-gEvEer|Price|price", re.I))
            price_text = price_el.get_text(" ", strip=True) if price_el else ""
            if not price_text:
                # Search for DH pattern in full text
                m = re.search(r"[\d\s]+DH", full_text)
                price_text = m.group(0) if m else "0"
            price = _parse_price(price_text)

            # Skip "Demander le prix" listings completely to avoid junk
            if price == 0:
                continue

            # Surface
            surface = _parse_surface(full_text)
            if surface == 0 and "surface" not in full_text.lower():
                # On Avito, surface is critical for quality. Skip if completely missing.
                continue

            # Rooms
            rooms = _parse_rooms(full_text)

            # Neighborhood / category
            detail_el = card.find(["p", "span"], class_=re.compile(r"sc-e|detail|location|category", re.I))
            detail_text = detail_el.get_text(" ", strip=True) if detail_el else full_text
            neighborhood = _extract_neighborhood(detail_text, city)

            # Type from URL path or card category
            prop_type = _parse_type(url + " " + detail_text)

            # Seller
            seller_el = card.find(["span", "p"], class_=re.compile(r"seller|Seller|account|Account", re.I))
            seller = seller_el.get_text(strip=True) if seller_el else "Particulier"
            if len(seller) > 60:
                seller = seller[:60]

            # Listing Date
            # Usually at the bottom in a span/p
            date_el = card.find(["span", "p"], class_=re.compile(r"sc-1nre5ec-4|date|time", re.I))
            date_listing = _parse_date(date_el.get_text(strip=True)) if date_el else now[:10]

            # Price per sqm
            ppsm = int(price / surface) if surface > 0 and price > 0 else 0

            # Category check: Avito sometimes shows rentals in sale results (sponsored)
            detected_txn = transaction
            if "louer" in full_text.lower() or "location" in full_text.lower():
                detected_txn = "Location"
            elif "vendre" in full_text.lower() or "vente" in full_text.lower():
                detected_txn = "Vente"

            listing = {
                "id": _make_id(url),
                "title": title[:200],
                "type": prop_type,
                "transaction": detected_txn,
                "city": city,
                "neighborhood": neighborhood,
                "surface": round(surface, 1),
                "rooms": rooms,
                "price": price,
                "price_per_sqm": ppsm,
                "source": "Avito.ma",
                "seller": seller[:80],
                "url": url,
                "status": "Vendu" if "vendu" in full_text.lower() else "Actif",
                "date_listing": date_listing,
                "date_transaction": None,
                "date_sold": now[:10] if "vendu" in full_text.lower() else None,
                "scraped_at": now,
            }
            results.append(listing)
        except Exception:
            continue

    return results


async def scrape_avito(
    log_queue: asyncio.Queue,
    pages_per_combo: int = 40,
) -> AsyncIterator[dict]:
    """
    Scrape Avito.ma across all cities and both transaction types.
    Yields individual listing dicts as they are scraped.
    Sends log messages to log_queue.
    """
    async def log(level: str, msg: str):
        await log_queue.put({"level": level, "msg": msg})

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for city_name, city_slug in CITY_SLUGS.items():
            for txn_label, mode_slug in MODES:
                city_total = 0
                for page in range(1, pages_per_combo + 1):
                    url = f"{BASE}/fr/{city_slug}/{mode_slug}?o={page}"
                    try:
                        headers = random.choice(HEADERS)
                        resp = await client.get(url, headers=headers)
                        if resp.status_code == 429:
                            await log("WARN", f"Rate limited on {city_name} ({txn_label}) p{page} — sleeping 5s")
                            await asyncio.sleep(5)
                            continue
                        if resp.status_code != 200:
                            await log("WARN", f"HTTP {resp.status_code} for {city_name} ({txn_label}) p{page}")
                            break

                        listings = _parse_cards(resp.text, city_name, txn_label)
                        if not listings:
                            # No more results on this page
                            await log("INFO", f"[Avito] {city_name} {txn_label}: no more results at p{page}")
                            break

                        for l in listings:
                            yield l

                        city_total += len(listings)
                        await log(
                            "DATA",
                            f"[Avito.ma] {city_name} · {txn_label} · p{page} → {len(listings)} listings ({city_total} total)"
                        )

                    except httpx.TimeoutException:
                        await log("WARN", f"Timeout on {city_name} ({txn_label}) p{page}, skipping")
                        break
                    except Exception as e:
                        await log("ERROR", f"Error scraping {city_name} p{page}: {e}")
                        break

                    # Polite delay
                    await asyncio.sleep(random.uniform(0.6, 1.4))

                await log("SUCCESS", f"[Avito.ma] {city_name} {txn_label} complete — {city_total} listings scraped")

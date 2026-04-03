"""
FastAPI backend — Morocco Real Estate Agent
Runs on port 8000. Frontend (Vite) runs on port 5173 and proxies /api/* here.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import db
from scraper.avito import scrape_avito
from scraper.mubawab import scrape_mubawab
from scraper.sarouty import scrape_sarouty

app = FastAPI(title="Morocco Real Estate Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

# ── Global job state ──────────────────────────────────────────────────────────

class JobState:
    def __init__(self):
        self.running = False
        self.log_queue: asyncio.Queue = asyncio.Queue()
        self.total_scraped = 0
        self.done = False
        self.error: Optional[str] = None

job = JobState()


async def run_scrape():
    job.running = True
    job.done = False
    job.error = None
    job.total_scraped = 0

    async def log(level: str, msg: str):
        now = datetime.utcnow().strftime("%H:%M:%S")
        await job.log_queue.put({"time": now, "level": level, "msg": msg})

    def is_sane(listing: dict) -> bool:
        """Global sanity filters to reject 'wrong data' outliers."""
        price = listing.get("price", 0)
        txn = listing.get("transaction", "")
        surface = listing.get("surface", 0)
        
        # 1. Price Thresholds (Skip placeholders like "1 DH" or "7 MAD")
        if price < 100: return False

        # Calculate price per sqm for validation
        ppsm = price / surface if surface > 0 else 0
        if ppsm > 150000: return False  # Hard safety limit for Morocco

        if txn == "Vente":
            if price < 20000: return False  # Real properties for sale start higher
            if price > 300000000: return False 
        elif txn == "Location":
            if price < 500: return False   # Minimum realistic rent
            if price > 200000: return False
            
        # 2. Surface Thresholds
        if surface < 10: return False      # Too small for a property
        if surface > 50000: return False   # Too large for standard analytics
        
        # 3. Required Fields
        if not listing.get("title") or len(listing["title"]) < 5: return False
        if not listing.get("city"): return False
        
        return True

    try:
        await log("INFO", "Initializing clean scrape - Wiping old data...")
        db.clear_listings()
        
        await log("INFO", "Agent initialized. Targeting Avito + Mubawab + Sarouty...")
        await log("INFO", "Applying strict validation filters (Min Sale: 10,000 MAD)")
        
        batch: list[dict] = []

        # ── Pipeline Runners ──
        sources = [
            ("Avito.ma", scrape_avito(job.log_queue, pages_per_combo=40)),
            ("Mubawab.ma", scrape_mubawab(job.log_queue, pages_per_combo=20)),
            ("Sarouty.ma", scrape_sarouty(job.log_queue, pages_per_combo=20)),
        ]

        for source_name, source_gen in sources:
            await log("INFO", f"── Phase: {source_name} scraping started ──")
            source_count = 0
            async for listing in source_gen:
                if not is_sane(listing):
                    continue
                    
                batch.append(listing)
                job.total_scraped += 1
                source_count += 1

                if len(batch) >= 50:
                    db.upsert_many(batch)
                    batch.clear()

            if batch:
                db.upsert_many(batch)
                batch.clear()
            
            await log("SUCCESS", f"{source_name} complete — {source_count:,} valid listings collected")

        total_in_db = db.count_listings()
        await log("SUCCESS", f"✓ Global Pipeline complete — {total_in_db:,} clean listings in database")
        await log("AGENT", "Agent entering standby mode. Dataset is ready.")

    except Exception as e:
        job.error = str(e)
        await log("ERROR", f"Pipeline error: {e}")

    finally:
        job.running = False
        job.done = True
        now = datetime.utcnow().strftime("%H:%M:%S")
        await job.log_queue.put({"time": now, "level": "DONE", "msg": "__DONE__"})


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/listings")
def get_listings(
    city: Optional[str] = Query(None),
    txn: Optional[str] = Query(None),
    prop_type: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
):
    listings = db.get_all_listings(city=city, txn=txn, prop_type=prop_type, q=q)
    return {"listings": listings, "total": len(listings)}


@app.get("/api/stats")
def get_stats():
    return db.get_stats()


@app.post("/api/scrape/start")
async def start_scrape(background_tasks: BackgroundTasks):
    if job.running:
        return {"ok": False, "msg": "Scrape already running"}

    # Drain old log queue
    while not job.log_queue.empty():
        try:
            job.log_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

    background_tasks.add_task(run_scrape)
    return {"ok": True, "msg": "Scrape started"}


@app.get("/api/scrape/status")
async def scrape_status():
    """Server-Sent Events stream of log messages."""
    async def event_stream():
        yield "data: " + json.dumps({"level": "INFO", "msg": "Connected to agent log stream"}) + "\n\n"
        while True:
            try:
                entry = await asyncio.wait_for(job.log_queue.get(), timeout=30.0)
                yield "data: " + json.dumps(entry) + "\n\n"
                if entry.get("msg") == "__DONE__":
                    break
            except asyncio.TimeoutError:
                # Keep-alive ping
                yield ": ping\n\n"
            except Exception:
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/scrape/running")
def scrape_running():
    return {
        "running": job.running,
        "done": job.done,
        "total": job.total_scraped,
        "error": job.error,
    }


@app.delete("/api/listings")
def delete_listings():
    db.clear_listings()
    return {"ok": True, "msg": "All listings cleared"}


@app.get("/api/export")
def export_csv():
    import io
    import csv
    
    listings = db.get_all_listings()
    if not listings:
        return {"ok": False, "msg": "No listings available to export"}

    def generate():
        yield "\ufeff" # UTF-8 BOM for Excel
        output = io.StringIO()
        fieldnames = [
            "id", "title", "type", "transaction", "city", "neighborhood", 
            "surface", "rooms", "price", "price_per_sqm", "status", 
            "date_listing", "date_transaction", "date_sold", 
            "source", "seller", "url", "scraped_at"
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        yield output.getvalue()
        output.truncate(0)
        output.seek(0)

        for row in listings:
            writer.writerow(row)
            yield output.getvalue()
            output.truncate(0)
            output.seek(0)

    headers = {
        "Content-Disposition": 'attachment; filename="morocco-real-estate-listings.csv"',
        "Content-Type": "text/csv; charset=utf-8"
    }
    
    return StreamingResponse(generate(), headers=headers)


@app.get("/api/health")
def health():
    return {"ok": True, "listings_in_db": db.count_listings()}

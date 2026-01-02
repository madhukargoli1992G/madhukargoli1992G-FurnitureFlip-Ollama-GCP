import os
import re
import json
import math
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

# ----------------------------
# Config
# ----------------------------
DEBUG = os.getenv("DEBUG", "0") == "1"
ENABLE_LIVE_COMPS = os.getenv("ENABLE_LIVE_COMPS", "0") == "1"

GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "")
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "")

# ----------------------------
# Models
# ----------------------------
class InterpretIn(BaseModel):
    message: str


# ----------------------------
# Helpers
# ----------------------------
PRICE_RE = re.compile(r"(\$?\s*\d{1,5}(?:\.\d{1,2})?)")

def safe_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def extract_price_from_text(text: str) -> Optional[float]:
    """
    Best-effort price extraction from a snippet/title.
    CSE often doesn't guarantee price fields, so this is heuristic.
    """
    if not text:
        return None
    m = PRICE_RE.search(text.replace(",", ""))
    if not m:
        return None
    val = m.group(1).replace("$", "").strip()
    return safe_float(val)

def google_cse_search(query: str, num: int = 5) -> List[Dict[str, Any]]:
    """
    Uses Google Programmable Search Engine API to get results with URLs.
    Returns list of: {title, url, snippet}
    """
    if not (GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX):
        return []

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_CSE_API_KEY,
        "cx": GOOGLE_CSE_CX,
        "q": query,
        "num": max(1, min(num, 10)),
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", []) or []
    out = []
    for it in items:
        out.append({
            "title": it.get("title"),
            "url": it.get("link"),
            "snippet": it.get("snippet", ""),
        })
    return out

def build_comps(item: str, brand: Optional[str] = None, condition: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Build comparable prices. If live comps enabled, use CSE to get URLs.
    Prices are heuristic from snippets. If price can't be extracted, we estimate.
    """
    item = (item or "").strip() or "item"
    brand_part = f"{brand} " if brand else ""
    cond_part = f" {condition}" if condition else ""
    q = f"{brand_part}{item}{cond_part} price"

    # ---- Live comps with URLs ----
    if ENABLE_LIVE_COMPS and GOOGLE_CSE_API_KEY and GOOGLE_CSE_CX:
        results = google_cse_search(q, num=5)
        comps: List[Dict[str, Any]] = []
        for res in results:
            title = res.get("title") or f"{brand_part}{item} (similar)"
            url = res.get("url")
            snippet = res.get("snippet", "")
            price = extract_price_from_text(title) or extract_price_from_text(snippet)

            # If we still can't find a price, keep a soft estimate
            if price is None:
                price = 0.0

            comps.append({
                "source": "Web (CSE)",
                "title": title,
                "price": round(float(price), 2),
                "url": url,
            })

        # If all prices are 0.0, fallback to estimates so pricing works
        if comps and all(c["price"] == 0.0 for c in comps):
            comps = []

        if comps:
            return comps

    # ---- Fallback (estimated comps, no URLs) ----
    base = 30.0
    if brand and brand.lower() in ("ikea",):
        base = 35.0
    if item.lower() in ("sofa", "couch", "sectional"):
        base = 250.0
    if item.lower() in ("table", "dining table"):
        base = 120.0
    if item.lower() in ("chair",):
        base = 35.0

    return [
        {"source": "Marketplace", "title": f"{brand_part}{item} (similar)", "price": round(base * 0.85, 2), "url": None},
        {"source": "Marketplace", "title": f"{brand_part}{item} (similar)", "price": round(base * 0.95, 2), "url": None},
        {"source": "Marketplace", "title": f"{brand_part}{item} (similar)", "price": round(base * 1.05, 2), "url": None},
        {"source": "Retail (est.)", "title": f"New {brand_part}{item} (estimate)", "price": round(base * 1.45, 2), "url": None},
    ]

def recommend_price(expected_price: Optional[float], comps: List[Dict[str, Any]]) -> Dict[str, Any]:
    prices = [c.get("price") for c in comps if isinstance(c.get("price"), (int, float)) and c.get("price") > 0]
    if not prices:
        # safe default
        rec = expected_price if expected_price else 50.0
        low = rec * 0.9
        high = rec * 1.1
        return {
            "recommended_price": round(rec, 2),
            "low": round(low, 2),
            "high": round(high, 2),
            "confidence": "low",
            "notes": ["Not enough real comp prices found; using your input / default estimate."]
        }

    avg = sum(prices) / len(prices)
    rec = expected_price if expected_price else avg
    # Nudge toward comps
    rec = (rec * 0.6) + (avg * 0.4)

    stdev = math.sqrt(sum((p - avg) ** 2 for p in prices) / len(prices))
    band = max(2.0, stdev)

    low = max(1.0, rec - band)
    high = rec + band

    confidence = "medium" if len(prices) >= 3 else "low"
    notes = []
    if expected_price:
        if expected_price < min(prices):
            notes.append(f"Your expected price (${expected_price:.0f}) is below comps; you could list higher.")
        elif expected_price > max(prices):
            notes.append(f"Your expected price (${expected_price:.0f}) is above comps; expect slower interest.")
        else:
            notes.append("Your expected price is within the comp range.")
    notes.append("List slightly higher if you can wait; price closer to low for quick sale.")
    notes.append("Good photos and clear pickup details increase conversion.")

    return {
        "recommended_price": round(rec, 2),
        "low": round(low, 2),
        "high": round(high, 2),
        "confidence": confidence,
        "notes": notes,
    }


# ----------------------------
# Main endpoint (matches your UI)
# ----------------------------
@app.post("/agent/interpret")
def agent_interpret(payload: InterpretIn):
    msg = payload.message or ""

    # 1) Initial intent detection (super simple — keep your existing LLM logic if you have it)
    # Your current system already detects category/brand; we keep minimal support.
    if msg.startswith("DETAILS:"):
        details = json.loads(msg.replace("DETAILS:", "", 1))
        item = details.get("item") or details.get("category") or "item"
        brand = details.get("brand")
        condition = details.get("condition")
        expected_price = safe_float(details.get("price") or details.get("price_expectation"))

        comps = build_comps(item=item, brand=brand, condition=condition)
        rec = recommend_price(expected_price, comps)

        return {
            "intent": "sell_item",
            "category": item,
            "extracted": details,
            "form": None,  # already collected
            "comps": comps,
            "recommendation": rec,
        }

    # Otherwise: treat as initial “sell item” message and return a form
    # (If your existing code already builds forms dynamically, keep it there — this is a baseline.)
    text = msg.lower()
    if "sell" in text:
        # quick heuristics
        brand = "IKEA" if "ikea" in text else None
        item = "chair" if "chair" in text else ("table" if "table" in text else ("sofa" if "sofa" in text or "couch" in text else "item"))

        form = {
            "title": f"Details for {brand + ' ' if brand else ''}{item}".strip(),
            "fields": [
                {"name": "price", "label": "Your expected price ($)", "type": "number", "required": True},
                {"name": "notes", "label": "Notes (optional)", "type": "text", "required": False},
                {"name": "shape", "label": "Shape", "type": "select", "options": ["Rectangle", "Round", "Square", "Other"], "required": False},
                {"name": "dimensions", "label": "Dimensions (L x W x H)", "type": "text", "required": False},
            ],
            "prefill": {"brand": brand, "item": item},
        }

        return {
            "intent": "sell_item",
            "category": item,
            "extracted": {"brand": brand, "item": item},
            "form": form,
            "comps": None,
            "recommendation": None,
        }

    return {"intent": "greeting", "message": "Hello! Tell me what furniture you want to sell."}

import os
import json
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st

# -----------------------------
# Config (from env)
# -----------------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000").rstrip("/")
INTERPRET_URL = os.getenv("INTERPRET_URL", f"{BACKEND_URL}/agent/interpret")

DEBUG_UI = os.getenv("DEBUG_UI", "1") == "1"

# Google CSE (optional URL enrichment later)
GOOGLE_CSE_API_KEY = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_CX = os.getenv("GOOGLE_CSE_CX", "").strip()

APP_TITLE = "FurnitureFlip"


# -----------------------------
# Backend call
# -----------------------------
def call_backend_interpret(message: str, retries: int = 2, timeout: int = 45) -> Dict[str, Any]:
    payload = {"message": message}
    last_err = None
    for _ in range(retries + 1):
        try:
            r = requests.post(INTERPRET_URL, json=payload, timeout=timeout)
            if r.status_code >= 400:
                return {"_error": f"Backend error {r.status_code}: {r.text[:500]}"}
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.6)
    return {"_error": f"Failed to reach backend: {last_err}"}


# -----------------------------
# Google CSE helpers (optional)
# -----------------------------
def _cse_search_top_url(query: str, timeout: int = 20) -> Optional[str]:
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return None
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": GOOGLE_CSE_API_KEY, "cx": GOOGLE_CSE_CX, "q": query, "num": 1},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("items") or []
        if not items:
            return None
        return items[0].get("link")
    except Exception:
        return None


def enrich_comp_urls_with_cse(comps: List[Dict[str, Any]], item_hint: Optional[str], brand_hint: Optional[str]) -> List[Dict[str, Any]]:
    # IMPORTANT: This function is NEVER called until comps exist.
    if not comps:
        return comps
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_CX:
        return comps

    if "cse_cache" not in st.session_state:
        st.session_state.cse_cache = {}

    cache: Dict[str, Optional[str]] = st.session_state.cse_cache

    enriched = []
    for c in comps:
        c2 = dict(c)
        url = c2.get("url")
        if url and str(url).lower() not in ("none", ""):
            enriched.append(c2)
            continue

        title = (c2.get("title") or "").strip()
        source = (c2.get("source") or "").strip()

        q_parts = []
        if brand_hint:
            q_parts.append(str(brand_hint))
        if item_hint:
            q_parts.append(str(item_hint))
        if title:
            q_parts.append(title)
        if source:
            q_parts.append(source)

        q = " ".join([p for p in q_parts if p]).strip()
        if not q:
            enriched.append(c2)
            continue

        ck = q.lower()
        if ck in cache:
            c2["url"] = cache[ck]
            enriched.append(c2)
            continue

        found = _cse_search_top_url(q)
        cache[ck] = found
        c2["url"] = found
        enriched.append(c2)

    st.session_state.cse_cache = cache
    return enriched


# -----------------------------
# Form rendering
# -----------------------------
def normalize_fields(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = form.get("fields") or []
    if not isinstance(fields, list):
        return []
    return [f for f in fields if isinstance(f, dict)]


def render_dynamic_form(form: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not form:
        return None

    st.subheader(form.get("title") or "Details")

    fields = normalize_fields(form)
    prefill = form.get("prefill") or {}
    if not isinstance(prefill, dict):
        prefill = {}

    values: Dict[str, Any] = {}

    with st.form("details_form", clear_on_submit=False):
        for f in fields:
            name = f.get("name") or f.get("key") or f.get("id")
            if not name:
                continue

            label = f.get("label") or name
            ftype = (f.get("type") or "text").lower()
            required = bool(f.get("required", False))
            help_txt = f.get("help") or f.get("help_text") or ""

            default = f.get("default", None)
            if name in prefill and prefill[name] not in (None, ""):
                default = prefill[name]

            if ftype in ("number", "float", "int"):
                dv = float(default) if default not in (None, "") else 0.0
                values[name] = st.number_input(label + (" *" if required else ""), value=dv, help=help_txt)

            elif ftype in ("select", "dropdown"):
                options = f.get("options") or []
                if not isinstance(options, list):
                    options = []
                if options:
                    idx = options.index(default) if default in options else 0
                    values[name] = st.selectbox(label + (" *" if required else ""), options=options, index=idx, help=help_txt)
                else:
                    values[name] = st.text_input(label + (" *" if required else ""), value=str(default or ""), help=help_txt)

            elif ftype in ("multiselect", "multi_select"):
                options = f.get("options") or []
                if not isinstance(options, list):
                    options = []
                dv = default if isinstance(default, list) else []
                values[name] = st.multiselect(label + (" *" if required else ""), options=options, default=dv, help=help_txt)

            elif ftype in ("checkbox", "bool", "boolean"):
                dv = bool(default) if default is not None else False
                values[name] = st.checkbox(label + (" *" if required else ""), value=dv, help=help_txt)

            elif ftype in ("textarea", "long_text"):
                values[name] = st.text_area(label + (" *" if required else ""), value=str(default or ""), help=help_txt)

            else:
                values[name] = st.text_input(label + (" *" if required else ""), value=str(default or ""), help=help_txt)

        submitted = st.form_submit_button("Submit details")

    if not submitted:
        return None

    # Required validation
    missing = []
    for f in fields:
        if not f.get("required", False):
            continue
        name = f.get("name") or f.get("key") or f.get("id")
        if not name:
            continue
        v = values.get(name)
        if v is None:
            missing.append(name)
        elif isinstance(v, str) and v.strip() == "":
            missing.append(name)
        elif isinstance(v, list) and len(v) == 0:
            missing.append(name)

    if missing:
        st.error(f"Please fill required fields: {', '.join(missing)}")
        return None

    return values


# -----------------------------
# Dashboard rendering
# -----------------------------
def render_comps(comps: List[Dict[str, Any]], item_hint: Optional[str], brand_hint: Optional[str]) -> None:
    st.subheader("Comparable Prices (Comps)")
    if not comps:
        st.info("No comps returned.")
        return

    # Safe: only enrich when comps exist
    comps = enrich_comp_urls_with_cse(comps, item_hint=item_hint, brand_hint=brand_hint)

    df = pd.DataFrame([{
        "source": c.get("source"),
        "title": c.get("title"),
        "price": c.get("price"),
        "url": c.get("url"),
    } for c in (comps or []])

    try:

            df["url"] = df["url"].fillna("")
            df["link"] = df["url"].apply(lambda u: f"[open]({u})" if isinstance(u, str) and u.startswtith("http") else "")

         st.dataframe(
	     df[["source", "title","price","link"]]
             use_container_width = True,
             column_config ={
                  "price": st.column_config.NumberColumn("price", format="$%.2f),
                  "link": st.column_config.MarkdownColumn("link"),
            },
        )
    except Exception:
        st.table(df)


def render_recommendation(rec: Dict[str, Any]) -> None:
    st.subheader("Pricing Recommendation")
    if not rec:
        st.info("No recommendation returned.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Recommended Price", f"${float(rec.get('recommended_price', 0)):.2f}")
    c2.metric("Low", f"${float(rec.get('low', 0)):.2f}")
    c3.metric("High", f"${float(rec.get('high', 0)):.2f}")

    st.caption(f"Confidence: {rec.get('confidence', 'unknown')}")
    notes = rec.get("notes") or []
    if isinstance(notes, list) and notes:
        st.markdown("**Notes**")
        for n in notes:
            st.write(f"• {n}")


# -----------------------------
# Streamlit State (IMPORTANT)
# -----------------------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)
st.caption("Chat → agent detects item → dynamic form → submit → comps + recommendation dashboard")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Store LAST RESPONSE (any intent)
if "last_agent" not in st.session_state:
    st.session_state.last_agent = None

# Store LAST SELL_ITEM RESPONSE (this is what we render the form from)
if "sell_context" not in st.session_state:
    st.session_state.sell_context = None

# Store merged details
if "form_data" not in st.session_state:
    st.session_state.form_data = None


if DEBUG_UI:
    with st.sidebar:
        st.subheader("Debug")
        st.write("BACKEND_URL:", BACKEND_URL)
        st.write("INTERPRET_URL:", INTERPRET_URL)
        st.write("CSE KEY set:", bool(GOOGLE_CSE_API_KEY))
        st.write("CSE CX set:", bool(GOOGLE_CSE_CX))


# Render chat history
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])


# Chat input
user_msg = st.chat_input('Say what you want to sell (e.g., "I want to sell a chair")')
if user_msg:
    st.session_state.messages.append({"role": "user", "content": user_msg})
    with st.chat_message("user"):
        st.markdown(user_msg)

    with st.chat_message("assistant"):
        st.write("Got it. I’m detecting details and preparing the next step.")
        resp = call_backend_interpret(user_msg)
        st.session_state.last_agent = resp

        if resp.get("_error"):
            st.error(resp["_error"])
        else:
            # IMPORTANT: Only set sell_context when intent is sell_item AND form exists
            intent = resp.get("intent")
            if intent == "sell_item" and resp.get("form"):
                st.session_state.sell_context = resp

            if DEBUG_UI:
                with st.expander("Debug: backend response", expanded=True):
                    st.json(resp)


# -----------------------------
# Always render the latest SELL form (never lose it)
# -----------------------------
ctx = st.session_state.sell_context or {}
form0 = ctx.get("form")

if form0:
    # Show the form
    submitted_values = render_dynamic_form(form0)

    # After submit: call backend with DETAILS
    if submitted_values:
        extracted = ctx.get("extracted") or {}
        if not isinstance(extracted, dict):
            extracted = {}

        merged = {**extracted, **submitted_values}
        st.session_state.form_data = merged

        details_msg = "DETAILS:" + json.dumps(merged)
        st.info("Generating comps + recommendation…")
        resp2 = call_backend_interpret(details_msg, timeout=70)
        st.session_state.last_agent = resp2

        if resp2.get("_error"):
            st.error(resp2["_error"])
        else:
            if DEBUG_UI:
                with st.expander("Debug: backend response (DETAILS)", expanded=False):
                    st.json(resp2)

            comps2 = resp2.get("comps")
            rec2 = resp2.get("recommendation")
            form2 = resp2.get("form")

            item_hint = merged.get("item") or extracted.get("item")
            brand_hint = merged.get("brand") or extracted.get("brand")

            if form2:
                st.warning("Backend still needs more details — please complete required fields.")
            if comps2:
                render_comps(comps2, item_hint=item_hint, brand_hint=brand_hint)
            if rec2:
                render_recommendation(rec2)
else:
    # If user only greeted, don't show errors—just wait for a sell request.
    pass

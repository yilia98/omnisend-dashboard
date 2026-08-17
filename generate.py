#!/usr/bin/env python3
"""
Omnisend Multi-Store Dashboard Generator — V2
Filter bar: Market × Channel × Type (Overview / Campaign / Automation / Form)
Three view modes, client-side JS switching.
"""

import os
import re
import html
import requests
from datetime import datetime, timedelta, timezone

# ─── Store config ─────────────────────────────────────────────────────────────
STORES = [
    {"id": "GT-US",      "flag": "🇺🇸", "label": "Giraffe Tools US",  "currency": "USD", "color": "#2563eb", "bg": "#eff6ff", "key_env": "API_KEY_GT_US"},
    {"id": "GT-CA",      "flag": "🇨🇦", "label": "Giraffe Tools CA",  "currency": "CAD", "color": "#dc2626", "bg": "#fef2f2", "key_env": "API_KEY_GT_CA"},
    {"id": "GT-UK",      "flag": "🇬🇧", "label": "Giraffe Tools UK",  "currency": "GBP", "color": "#7c3aed", "bg": "#f5f3ff", "key_env": "API_KEY_GT_UK"},
    {"id": "GT-AU",      "flag": "🇦🇺", "label": "Giraffe Tools AU",  "currency": "AUD", "color": "#ea580c", "bg": "#fff7ed", "key_env": "API_KEY_GT_AU"},
    {"id": "GT-DE",      "flag": "🇩🇪", "label": "Giraffe Tools DE",  "currency": "EUR", "color": "#ca8a04", "bg": "#fefce8", "key_env": "API_KEY_GT_DE"},
    {"id": "GT-JP",      "flag": "🇯🇵", "label": "Giraffe Tools JP",  "currency": "JPY", "color": "#db2777", "bg": "#fdf2f8", "key_env": "API_KEY_GT_JP"},
    {"id": "Gitryin-US", "flag": "⚡",   "label": "Gitryin US",        "currency": "USD", "color": "#0891b2", "bg": "#ecfeff", "key_env": "API_KEY_GITRYIN_US"},
]

STORE_MAP = {s["id"]: s for s in STORES}

BASE = "https://api.omnisend.com"

TRIGGER_MAP = {
    "Subscribed to Marketing": "Welcome",
    "Started checkout":        "Checkout Abandon",
    "Added product to cart":   "Cart Abandon",
    "Viewed product":          "Product Abandon",
    "Viewed page":             "Browse Abandon",
    "Placed order":            "Post-Purchase",
    "Ordered product":         "Post-Purchase",
    "Entered segment":         "Lifecycle",
}

CAT_ICONS = {
    "Welcome":          "👋",
    "Checkout Abandon": "🛒",
    "Cart Abandon":     "🛒",
    "Product Abandon":  "👁",
    "Browse Abandon":   "👁",
    "Post-Purchase":    "📦",
    "Reactivation":     "🔄",
    "Anniversary":      "🎂",
    "Lifecycle":        "🎯",
    "Other":            "🔧",
}


# ─── API helpers ──────────────────────────────────────────────────────────────
def _hdrs(key):
    ver = datetime.now(timezone.utc).strftime("%Y-%m-01")
    return {"X-API-KEY": key, "Content-Type": "application/json", "Omnisend-Version": ver}


def safe_get(url, key, params=None):
    try:
        r = requests.get(url, headers=_hdrs(key), params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
        print(f"  GET {url} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  GET {url} → {e}")
    return {}


def safe_post(url, key, payload):
    try:
        r = requests.post(url, headers=_hdrs(key), json=payload, timeout=20)
        if r.status_code == 200:
            return r.json()
        print(f"  POST {url} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  POST {url} → {e}")
    return {}


# ─── Data fetchers ────────────────────────────────────────────────────────────
def fetch_analytics(key, date_from, date_to):
    data = safe_post(f"{BASE}/api/analytics/reports", key, {"queries": [
        {
            "alias": "totals",
            "dateRange": {"interval": "custom", "from": date_from, "to": date_to},
            "metrics": [
                {"name": "sent"}, {"name": "openRate"}, {"name": "clickRate"},
                {"name": "attributedRevenue"}, {"name": "unsubscribeRate"},
                {"name": "totalRevenue"}, {"name": "attributedOrders"},
            ],
        },
    ]})
    rpts = data.get("reports", [])
    totals = rpts[0].get("rows", [{}])[0] if rpts else {}
    # by_type in its own self-healing call so the richer metric set (opened /
    # clicked / markedAsSpamRate) can't break the totals query.
    by_rows = _report_rows(key, date_from, date_to, ["marketingActivityType"], PERF_METRICS)
    by_type = {row.get("marketingActivityType", "Unknown"): row for row in by_rows}
    return {"totals": totals, "by_type": by_type}


def fetch_analytics_growth(key, date_from, date_to):
    """Fetch subscriber growth for a given date range."""
    if date_from[:4] != date_to[:4]:
        date_from = f"{date_to[:4]}-01-01T00:00:00Z"
    data = safe_post(f"{BASE}/api/analytics/statistics", key, {"queries": [
        {
            "alias": "growth",
            "dateRange": {"from": date_from, "to": date_to},
            "dimensions": [{"name": "timestamp", "granularity": "day"}],
            "metrics": [
                {"name": "subscribedEmail"},
                {"name": "unsubscribedEmail"},
                {"name": "subscribedSms"},
            ],
        }
    ]})
    rows = ((data.get("statistics") or [{}])[0]).get("rows", [])
    out = {"subscribedEmail": 0, "unsubscribedEmail": 0, "subscribedSms": 0}
    for row in rows:
        for k in out:
            out[k] += row.get(k) or 0
    return out


def fetch_subscriber_growth(key, date_from, date_to):
    return fetch_analytics_growth(key, date_from, date_to)


def _pick(d, *keys):
    """Return the first non-None value from d for the given keys."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def fetch_campaigns(key, n=30):
    data = safe_get(f"{BASE}/api/campaigns", key,
                    {"status": "sent", "limit": n, "sort": "updatedAt", "direction": "desc"})
    items = []
    for c in data.get("campaigns", []):
        ch = c.get("channel", "email").lower()
        ch_label = {"email": "EDM", "sms": "SMS", "push": "Push"}.get(ch, ch.upper())
        items.append({
            "id":      c.get("id", ""),
            "name":    c.get("content", {}).get("email", {}).get("subject") or c.get("name", "—"),
            "channel": ch_label,
            "status":  c.get("status", "—"),
            "sent_at": c.get("startedAt") or c.get("createdAt", ""),
        })
    return items


def fetch_campaign_stats(key, date_from, date_to):
    """Per-campaign performance via the analytics *reports* endpoint (the one that
    accepts rate/revenue metrics; /statistics does not). Omnisend models
    campaigns as 'marketing activities', so the per-campaign dimension is
    marketingActivityID (parallel to the working marketingActivityType). Account
    dialects vary, so we probe a few candidate dimension names and use whichever
    the API accepts. OPENS/CLICKS are derived as rate × sent (openRate is a
    unique-open rate, so OPENS is unique opens — consistent with Open%)."""
    metrics = [
        {"name": "sent"}, {"name": "openRate"}, {"name": "clickRate"},
        {"name": "attributedRevenue"}, {"name": "attributedOrders"},
        {"name": "unsubscribeRate"},
    ]
    candidates = ["marketingActivityID", "marketingActivityId", "marketingActivity",
                  "campaignID", "campaignId", "campaign"]
    rows, used_dim = [], None
    for dim in candidates:
        try:
            r = requests.post(f"{BASE}/api/analytics/reports", headers=_hdrs(key),
                              json={"queries": [{
                                  "alias": "by_camp",
                                  "dateRange": {"interval": "custom", "from": date_from, "to": date_to},
                                  "dimensions": [{"name": dim}],
                                  "metrics": metrics,
                              }]}, timeout=25)
        except Exception as e:
            print(f"  camp_stats dim={dim} EXC {e}")
            continue
        if r.status_code != 200:
            print(f"  camp_stats dim={dim} → {r.status_code}: {r.text[:400]}")
            continue
        reps = r.json().get("reports", [])
        rr = reps[0].get("rows", []) if reps else []
        print(f"  camp_stats dim={dim} OK rows={len(rr)}"
              + (f" keys={list(rr[0].keys())}" if rr else ""))
        if rr:
            rows, used_dim = rr, dim
            break

    out = {}
    for r in rows:
        cid = (r.get(used_dim) if used_dim else None) or r.get("marketingActivityID") \
              or r.get("campaignID") or r.get("campaignId")
        if not cid:
            continue
        sent  = r.get("sent")
        orate = r.get("openRate")
        crate = r.get("clickRate")
        out[cid] = {
            "sent":      sent,
            "openRate":  orate,
            "clickRate": crate,
            "revenue":   r.get("attributedRevenue"),
            "orders":    r.get("attributedOrders"),
            "unsubRate": r.get("unsubscribeRate"),
            "opens":     round(orate * sent) if (orate is not None and sent) else None,
            "clicks":    round(crate * sent) if (crate is not None and sent) else None,
        }
    print(f"  campaign_stats final rows={len(out)} dim={used_dim}")
    return out


# Metrics available on /reports for the campaign/automation/message dimensions
# (confirmed by probe). placedOrderRate/failedDeliveryRate are NOT available —
# Placed-Order% is derived as orders/sent; failed-delivery is omitted.
PERF_METRICS = ["sent", "openRate", "clickRate", "attributedRevenue",
                "attributedOrders", "unsubscribeRate", "markedAsSpamRate",
                "opened", "clicked"]


def _report_rows(key, date_from, date_to, dims, metrics):
    """POST /reports for the given dimensions, self-healing by dropping any
    metric the API rejects. Returns the list of rows."""
    m = list(metrics)
    for _ in range(len(metrics) + 1):
        try:
            r = requests.post(f"{BASE}/api/analytics/reports", headers=_hdrs(key),
                              json={"queries": [{
                                  "alias": "q",
                                  "dateRange": {"interval": "custom", "from": date_from, "to": date_to},
                                  "dimensions": [{"name": d} for d in dims],
                                  "metrics": [{"name": x} for x in m],
                              }]}, timeout=30)
        except Exception as e:
            print(f"  report {dims} EXC {e}")
            return []
        if r.status_code == 200:
            reps = r.json().get("reports", [])
            return reps[0].get("rows", []) if reps else []
        bad = set()
        try:
            for e in r.json().get("errors", []):
                mm = re.search(r"metrics\[(\d+)\]", e.get("field", ""))
                if mm:
                    bad.add(int(mm.group(1)))
        except Exception:
            pass
        if not bad:
            print(f"  report {dims} → {r.status_code}: {r.text[:200]}")
            return []
        m = [x for i, x in enumerate(m) if i not in bad]
        if not m:
            return []
    return []


def _norm_perf(r):
    return {
        "sent":      r.get("sent"),
        "openRate":  r.get("openRate"),
        "clickRate": r.get("clickRate"),
        "revenue":   r.get("attributedRevenue"),
        "orders":    r.get("attributedOrders"),
        "unsubRate": r.get("unsubscribeRate"),
        "spamRate":  r.get("markedAsSpamRate"),
        "opens":     r.get("opened"),
        "clicks":    r.get("clicked"),
    }


def fetch_automation_stats(key, date_from, date_to):
    """Per-automation-flow metrics (dim=marketingActivityID) and per-message
    metrics (dim=messageID), for the Automation table + its Email/SMS drill-down."""
    flow_rows = _report_rows(key, date_from, date_to, ["marketingActivityID"], PERF_METRICS)
    msg_rows  = _report_rows(key, date_from, date_to, ["messageID"], PERF_METRICS)
    flow = {r.get("marketingActivityID"): _norm_perf(r)
            for r in flow_rows if r.get("marketingActivityID")}
    msg  = {r.get("messageID"): _norm_perf(r)
            for r in msg_rows if r.get("messageID")}
    print(f"  automation_stats flow={len(flow)} msg={len(msg)}")
    return {"flow": flow, "msg": msg}


def fetch_automations(key):
    data = safe_get(f"{BASE}/v5/automations", key)
    items = data.get("automations", [])

    by_status = {"enabled": 0, "disabled": 0, "draft": 0}
    by_cat = {}
    ch_msgs = {"email": 0, "sms": 0, "push": 0}
    auto_rows = []

    for a in items:
        st = a.get("status", "draft")
        by_status[st] = by_status.get(st, 0) + 1

        trigger = a.get("trigger", "")
        cat = TRIGGER_MAP.get(trigger, "Other")

        if trigger == "Entered segment":
            nm = a.get("name", "").lower()
            if any(x in nm for x in ["welcome"]):
                cat = "Welcome"
            elif any(x in nm for x in ["re-", "re_", "reactivat", "sunset",
                                        "attention", "miss", "cherish", "at risk",
                                        "about to", "lost", "last call"]):
                cat = "Reactivation"
            elif any(x in nm for x in ["anniversary", "birthday"]):
                cat = "Anniversary"
            elif any(x in nm for x in ["review", "recent customer",
                                        "post", "cross", "upsell", "reward"]):
                cat = "Post-Purchase"

        entry = by_cat.setdefault(cat, {"enabled": 0, "total": 0})
        entry["total"] += 1
        if st == "enabled":
            entry["enabled"] += 1

        msgs = a.get("messages", [])
        channels = list({m.get("channel", "email") for m in msgs})
        for m in msgs:
            ch = m.get("channel", "email")
            ch_msgs[ch] = ch_msgs.get(ch, 0) + 1

        ch_labels = [{"email": "EDM", "sms": "SMS", "push": "Push"}.get(c, c.upper()) for c in channels]
        msg_list = [{"id": m.get("id", ""),
                     "title": m.get("title") or "",
                     "channel": m.get("channel", "email")} for m in msgs]
        auto_rows.append({
            "id":       a.get("id", ""),
            "name":     a.get("name", "—"),
            "status":   st,
            "category": cat,
            "channels": ", ".join(ch_labels) if ch_labels else "—",
            "trigger":  trigger or "—",
            "messages": msg_list,
        })

    return {
        "total":     len(items),
        "active":    by_status.get("enabled", 0),
        "by_status": by_status,
        "by_cat":    by_cat,
        "ch_msgs":   ch_msgs,
        "rows":      auto_rows,
    }


def fetch_forms(key):
    data = safe_get(f"{BASE}/api/forms", key, {"limit": 50})
    items = []
    for f in data.get("forms", []):
        stats = f.get("statistics", {})
        items.append({
            "name":             f.get("name", "—"),
            "type":             f.get("type", "—"),
            "status":           f.get("status", "—"),
            "views":            stats.get("views"),
            "interaction_rate": stats.get("interactionRate"),
            "submit_rate":      stats.get("submitRate"),
            "signup_rate":      stats.get("signupRate"),
        })
    return items


def fetch_segments(key):
    data = safe_get(f"{BASE}/api/segments", key, {"limit": 50})
    segs = data.get("segments", [])
    more = data.get("paging", {}).get("hasMore", False)
    return {"count": len(segs), "plus": more}


# ─── Formatters ───────────────────────────────────────────────────────────────
def fmt_num(n):
    return f"{int(n):,}" if n is not None else "—"

def fmt_pct(n, decimals=2):
    return f"{n * 100:.{decimals}f}%" if n is not None else "—"

def fmt_rev(n, cur):
    if n is None:
        return "—"
    sym = {"USD": "$", "CAD": "CA$", "GBP": "£", "AUD": "A$", "EUR": "€", "JPY": "¥"}.get(cur, cur + " ")
    return f"{sym}{int(n):,}" if cur == "JPY" else f"{sym}{n:,.0f}"

def fmt_date(iso):
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y")
    except Exception:
        return iso[:10]

def open_cls(r):
    if r is None: return "h-gray"
    p = r * 100
    return "h-green" if p >= 45 else ("h-yellow" if p >= 35 else "h-red")

def unsub_cls(r):
    if r is None: return "h-gray"
    p = r * 100
    return "h-green" if p <= 0.4 else ("h-yellow" if p <= 0.7 else "h-red")

def ctr_cls(r):
    if r is None: return "h-gray"
    p = r * 100
    return "h-green" if p >= 2.5 else ("h-yellow" if p >= 1.5 else "h-red")

def growth_cls(net):
    if net is None: return "h-gray"
    return "h-green" if net > 0 else ("h-red" if net < 0 else "h-gray")

def status_cls(st):
    return {"enabled": "status-on", "sent": "status-on", "disabled": "status-off",
            "draft": "status-draft", "paused": "status-off"}.get(st, "status-draft")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    now          = datetime.now(timezone.utc)
    PICKER_DAYS  = 92          # how far back the custom-range picker may go
    STAT_DAYS    = 120         # window for per-campaign stats (covers recent campaigns)
    date_to      = now.strftime("%Y-%m-%dT23:59:59Z")
    date_from_30 = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    date_from_7  = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    date_from_stat  = (now - timedelta(days=STAT_DAYS)).strftime("%Y-%m-%dT00:00:00Z")
    display_30   = f"{(now - timedelta(days=30)).strftime('%b %d')} – {now.strftime('%b %d, %Y')}"
    display_7    = f"{(now - timedelta(days=7)).strftime('%b %d')} – {now.strftime('%b %d, %Y')}"
    updated_at   = now.strftime("%Y-%m-%d %H:%M UTC")
    range_min    = (now - timedelta(days=PICKER_DAYS)).strftime("%Y-%m-%d")
    range_max    = now.strftime("%Y-%m-%d")

    store_data = []

    empty_analytics = {"totals": {}, "by_type": {}}
    empty_growth    = {"subscribedEmail": 0, "unsubscribedEmail": 0, "subscribedSms": 0}
    empty_auto      = {"total": 0, "active": 0, "by_status": {}, "by_cat": {}, "ch_msgs": {}, "rows": []}

    for s in STORES:
        key = os.environ.get(s["key_env"], "")
        if not key:
            print(f"⚠️  No key for {s['id']}, skipping.")
            store_data.append({**s,
                "analytics_30": empty_analytics,
                "analytics_7":  empty_analytics,
                "growth_30":    empty_growth,
                "growth_7":     empty_growth,
                "automations":  empty_auto,
                "segments":     {"count": 0, "plus": False},
                "campaigns":    [],
                "camp_stats":   {},
                "auto_stats_30": {"flow": {}, "msg": {}},
                "auto_stats_7":  {"flow": {}, "msg": {}},
                "forms":        [],
            })
            continue

        print(f"Fetching {s['id']}…")
        store_data.append({**s,
            "analytics_30": fetch_analytics(key, date_from_30, date_to),
            "analytics_7":  fetch_analytics(key, date_from_7, date_to),
            "growth_30":    fetch_analytics_growth(key, date_from_30, date_to),
            "growth_7":     fetch_analytics_growth(key, date_from_7, date_to),
            "automations":  fetch_automations(key),
            "segments":     fetch_segments(key),
            "campaigns":    fetch_campaigns(key, 30),
            "camp_stats":   fetch_campaign_stats(key, date_from_stat, date_to),
            "auto_stats_30": fetch_automation_stats(key, date_from_30, date_to),
            "auto_stats_7":  fetch_automation_stats(key, date_from_7, date_to),
            "forms":        fetch_forms(key),
        })

    html = build_html(store_data, display_30, display_7, updated_at, range_min, range_max)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅  index.html generated.")


# ─── HTML builder ─────────────────────────────────────────────────────────────
def build_html(stores, display_30, display_7, updated_at, range_min="", range_max=""):

    import json as _json

    store_ids = [s["id"] for s in stores]

    # ── Market options for filter dropdown ──
    market_opts = '<option value="all">All Markets</option>\n'
    for s in stores:
        market_opts += f'      <option value="{s["id"]}">{s["flag"]} {s["id"]}</option>\n'

    # ── Embed analytics summary as JSON for JS date-range switching ──
    def _totals_json(range_key):
        out = {}
        for s in stores:
            a = s[f"analytics_{range_key}"]["totals"]
            bt = s[f"analytics_{range_key}"]["by_type"]
            g  = s[f"growth_{range_key}"]
            sub = g.get("subscribedEmail", 0) or 0
            uns = g.get("unsubscribedEmail", 0) or 0
            sms = g.get("subscribedSms", 0) or 0
            camp = bt.get("Campaign", {})
            auto_t = bt.get("Automation", {})
            out[s["id"]] = {
                "sent":        a.get("sent"),
                "openRate":    a.get("openRate"),
                "clickRate":   a.get("clickRate"),
                "revenue":     a.get("attributedRevenue"),
                "totalRev":    a.get("totalRevenue"),
                "orders":      a.get("attributedOrders"),
                "unsubRate":   a.get("unsubscribeRate"),
                "subEmail":    sub,
                "unsubEmail":  uns,
                "netGrowth":   sub - uns,
                "subSms":      sms,
                "campSent":    camp.get("sent"),
                "campOpen":    camp.get("openRate"),
                "campRev":     camp.get("attributedRevenue"),
                "campOrders":  camp.get("attributedOrders"),
                "autoSent":    auto_t.get("sent"),
                "autoOpen":    auto_t.get("openRate"),
                "autoRev":     auto_t.get("attributedRevenue"),
                "autoOrders":  auto_t.get("attributedOrders"),
                "autoOpens":   auto_t.get("opened"),
                "autoClicks":  auto_t.get("clicked"),
                "autoUnsub":   auto_t.get("unsubscribeRate"),
                "autoSpam":    auto_t.get("markedAsSpamRate"),
                "currency":    s["currency"],
                "color":       s["color"],
            }
        return out

    data_30_json = _json.dumps(_totals_json("30"), ensure_ascii=False)
    data_7_json  = _json.dumps(_totals_json("7"),  ensure_ascii=False)

    # Per-flow + per-message automation stats for 30d / 7d, so the Workflow
    # Performance table can switch with the time range (filtered to the ids that
    # actually appear in the table to keep the payload small).
    def _auto_switch(range_key):
        out = {}
        for s in stores:
            astats = s.get(f"auto_stats_{range_key}", {"flow": {}, "msg": {}})
            fmap, mmap = astats.get("flow", {}), astats.get("msg", {})
            wf, wm = {}, {}
            for row in s["automations"].get("rows", []):
                aid = row.get("id")
                if aid in fmap:
                    wf[aid] = fmap[aid]
                for m in row.get("messages", []):
                    mid = m.get("id")
                    if mid in mmap:
                        wm[mid] = mmap[mid]
            out[s["id"]] = {"flow": wf, "msg": wm}
        return out

    auto_30_json = _json.dumps(_auto_switch("30"), ensure_ascii=False)
    auto_7_json  = _json.dumps(_auto_switch("7"),  ensure_ascii=False)

    # ────────────────────────────────────────────────────────────────────────
    # VIEW 1 — Overview: KPI cards (values updated by JS; show 30d by default)
    # ────────────────────────────────────────────────────────────────────────
    cards_html = ""
    for s in stores:
        a    = s["analytics_30"]["totals"]
        auto = s["automations"]
        cards_html += f"""
        <div class="card" data-store="{s['id']}" style="border-top:3px solid {s['color']}">
          <div class="card-header">
            <span class="store-badge" style="background:{s['bg']};color:{s['color']}">{s['flag']} {s['id']}</span>
            <span class="card-currency">{s['currency']}</span>
          </div>
          <div class="card-name">{s['label']}</div>
          <div class="card-metrics">
            <div class="metric-box">
              <div class="m-label" id="lbl-sent-{s['id']}">Sent</div>
              <div class="m-value" id="val-sent-{s['id']}" style="color:{s['color']}">{fmt_num(a.get('sent'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">Open Rate</div>
              <div class="m-value" id="val-open-{s['id']}">{fmt_pct(a.get('openRate'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">CTR</div>
              <div class="m-value" id="val-ctr-{s['id']}">{fmt_pct(a.get('clickRate'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">Revenue</div>
              <div class="m-value" id="val-rev-{s['id']}">{fmt_rev(a.get('attributedRevenue'), s['currency'])}</div>
            </div>
          </div>
          <div class="card-footer">
            <span id="val-orders-{s['id']}">📦 {fmt_num(a.get('attributedOrders'))} orders</span>
            <span>⚡ {auto['active']}/{auto['total']} flows</span>
          </div>
        </div>"""

    # Analytics table rows — rendered with 30d data; JS updates on range switch
    analytics_rows = ""
    for s in stores:
        a = s["analytics_30"]["totals"]
        analytics_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num" id="tbl-sent-{s['id']}">{fmt_num(a.get('sent'))}</td>
          <td id="tbl-open-{s['id']}"><span class="heat {open_cls(a.get('openRate'))}">{fmt_pct(a.get('openRate'))}</span></td>
          <td id="tbl-ctr-{s['id']}"><span class="heat {ctr_cls(a.get('clickRate'))}">{fmt_pct(a.get('clickRate'))}</span></td>
          <td class="num" id="tbl-rev-{s['id']}">{fmt_rev(a.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted" id="tbl-trev-{s['id']}">{fmt_rev(a.get('totalRevenue'), s['currency'])}</td>
          <td class="num fw6" id="tbl-orders-{s['id']}">{fmt_num(a.get('attributedOrders'))}</td>
          <td id="tbl-unsub-{s['id']}"><span class="heat {unsub_cls(a.get('unsubscribeRate'))}">{fmt_pct(a.get('unsubscribeRate'))}</span></td>
        </tr>"""

    # Campaign vs Automation split
    split_rows = ""
    for s in stores:
        bt   = s["analytics_30"]["by_type"]
        camp = bt.get("Campaign", {})
        auto = bt.get("Automation", {})
        split_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num" id="sp-csent-{s['id']}">{fmt_num(camp.get('sent'))}</td>
          <td id="sp-copen-{s['id']}"><span class="heat {open_cls(camp.get('openRate'))}">{fmt_pct(camp.get('openRate'))}</span></td>
          <td class="num" id="sp-crev-{s['id']}">{fmt_rev(camp.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted" id="sp-corders-{s['id']}">{fmt_num(camp.get('attributedOrders'))}</td>
          <td class="divider-col"></td>
          <td class="num" id="sp-asent-{s['id']}">{fmt_num(auto.get('sent'))}</td>
          <td id="sp-aopen-{s['id']}"><span class="heat {open_cls(auto.get('openRate'))}">{fmt_pct(auto.get('openRate'))}</span></td>
          <td class="num" id="sp-arev-{s['id']}">{fmt_rev(auto.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted" id="sp-aorders-{s['id']}">{fmt_num(auto.get('attributedOrders'))}</td>
        </tr>"""

    # Growth rows
    growth_rows = ""
    for s in stores:
        g   = s["growth_30"]
        sub = g.get("subscribedEmail", 0) or 0
        uns = g.get("unsubscribedEmail", 0) or 0
        sms = g.get("subscribedSms", 0) or 0
        net = sub - uns
        growth_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num pos" id="gr-sub-{s['id']}">{fmt_num(sub)}</td>
          <td class="num neg" id="gr-uns-{s['id']}">−{fmt_num(uns)}</td>
          <td id="gr-net-{s['id']}"><span class="heat {growth_cls(net)}">{'+' if net > 0 else ''}{fmt_num(net)}</span></td>
          <td class="num muted" id="gr-sms-{s['id']}">{fmt_num(sms) if sms else '—'}</td>
        </tr>"""

    # Segment bars (static, not date-dependent)
    max_seg  = max((s["segments"]["count"] for s in stores), default=1)
    seg_rows = ""
    for s in stores:
        seg   = s["segments"]
        label = f"{seg['count']}+" if seg["plus"] else str(seg["count"])
        width = round(seg["count"] / max(max_seg, 1) * 100)
        seg_rows += f"""
        <div class="prog-row" data-store="{s['id']}">
          <div class="prog-label" style="color:{s['color']}">{s['id']}</div>
          <div class="prog-track">
            <div class="prog-fill" style="width:{max(width,4)}%;background:{s['color']};opacity:.75"></div>
          </div>
          <div class="prog-count">{label}</div>
        </div>"""

    # ────────────────────────────────────────────────────────────────────────
    # VIEW 2 — Campaign detail table
    # ────────────────────────────────────────────────────────────────────────
    camp_rows = ""
    for s in stores:
        cstats = s.get("camp_stats", {})
        for c in s["campaigns"]:
            ch = c["channel"]
            ch_cls = {"EDM": "tag-email", "SMS": "tag-sms", "Push": "tag-push"}.get(ch, "tag-email")
            st_cls = status_cls(c["status"])
            st = cstats.get(c.get("id", ""), {})
            sent   = st.get("sent")
            orate  = st.get("openRate")
            crate  = st.get("clickRate")
            opens  = st.get("opens")
            clicks = st.get("clicks")
            rev    = st.get("revenue")
            orders = st.get("orders")
            unsub  = st.get("unsubRate")
            nm_esc = html.escape(c["name"], quote=True)
            camp_rows += f"""
        <tr data-store="{s['id']}" data-channel="{ch}" data-sent-at="{c['sent_at']}" data-in-range="1"
            data-cur="{s['currency']}"
            data-name="{nm_esc}"
            data-status="{c['status']}"
            data-sent="{sent if sent is not None else ''}"
            data-open="{orate if orate is not None else ''}"
            data-ctr="{crate if crate is not None else ''}"
            data-opens="{opens if opens is not None else ''}"
            data-clicks="{clicks if clicks is not None else ''}"
            data-rev="{rev if rev is not None else ''}"
            data-orders="{orders if orders is not None else ''}"
            data-unsub="{unsub if unsub is not None else ''}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span>{s['flag']} {s['id']}</span>
          </div></td>
          <td class="camp-name" title="{nm_esc}">{nm_esc}</td>
          <td><span class="tag {ch_cls}">{ch}</span></td>
          <td class="muted small">{fmt_date(c['sent_at'])}</td>
          <td><span class="{st_cls}">{c['status']}</span></td>
          <td class="num">{fmt_num(sent)}</td>
          <td><span class="heat {ctr_cls(crate)}">{fmt_pct(crate)}</span></td>
          <td><span class="heat {open_cls(orate)}">{fmt_pct(orate)}</span></td>
          <td class="num">{fmt_num(opens)}</td>
          <td class="num">{fmt_num(clicks)}</td>
          <td class="num fw6">{fmt_rev(rev, s['currency'])}</td>
          <td class="num">{fmt_num(orders)}</td>
          <td><span class="heat {unsub_cls(unsub)}">{fmt_pct(unsub)}</span></td>
        </tr>"""

    if not camp_rows:
        camp_rows = '<tr class="empty-row"><td colspan="13">No campaign data available</td></tr>'

    # ────────────────────────────────────────────────────────────────────────
    # VIEW 3 — Automation detail table
    # ────────────────────────────────────────────────────────────────────────
    auto_rows_html = ""
    # Also build summary progress bars
    auto_progress = ""
    cat_rows = ""
    ch_stats_html = ""

    total_ch = {}
    for s in stores:
        for ch, cnt in s["automations"].get("ch_msgs", {}).items():
            total_ch[ch] = total_ch.get(ch, 0) + cnt

    ch_stats_html = f"""<div class="ch-stat" data-ch="all">
        <div class="ch-item"><span class="ch-dot" style="background:#1d4ed8"></span>Email: {fmt_num(total_ch.get('email'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#16a34a"></span>SMS: {fmt_num(total_ch.get('sms'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#7c3aed"></span>Push: {fmt_num(total_ch.get('push'))}</div>
      </div>"""
    for s in stores:
        ch = s["automations"].get("ch_msgs", {})
        ch_stats_html += f"""
      <div class="ch-stat" data-ch="{s['id']}" hidden>
        <div class="ch-item"><span class="ch-dot" style="background:#1d4ed8"></span>Email: {fmt_num(ch.get('email'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#16a34a"></span>SMS: {fmt_num(ch.get('sms'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#7c3aed"></span>Push: {fmt_num(ch.get('push'))}</div>
      </div>"""

    for s in stores:
        auto  = s["automations"]
        total = max(auto["total"], 1)
        pct   = round(auto["active"] / total * 100)
        bs    = auto.get("by_status", {})
        auto_progress += f"""
        <div class="prog-row" data-store="{s['id']}">
          <div class="prog-label" style="color:{s['color']}">{s['id']}</div>
          <div class="prog-track">
            <div class="prog-fill" style="width:{pct}%;background:{s['color']}"></div>
          </div>
          <div class="prog-meta">
            <span class="fw6">{auto['active']}/{auto['total']}</span>
            <span class="pill pill-green">{bs.get('enabled',0)} on</span>
            <span class="pill pill-gray">{bs.get('disabled',0)} off</span>
            <span class="pill pill-dim">{bs.get('draft',0)} draft</span>
          </div>
        </div>"""

        is_default = s["id"] == "GT-US"
        for cat, counts in sorted(auto.get("by_cat", {}).items(), key=lambda x: -x[1]["total"]):
            icon    = CAT_ICONS.get(cat, "🔧")
            enabled = counts["enabled"]
            total_c = counts["total"]
            pct_c   = round(enabled / max(total_c, 1) * 100)
            hidden_attr = "" if is_default else " hidden"
            cat_rows += f"""
            <div class="cat-row" data-store="{s['id']}"{hidden_attr}>
              <div class="cat-label">{icon} {cat}</div>
              <div class="prog-track" style="flex:1;margin:0 10px">
                <div class="prog-fill" style="width:{pct_c}%;background:{s['color']}"></div>
              </div>
              <div class="cat-count">{enabled}/{total_c} active</div>
            </div>"""

        astats  = s.get("auto_stats_30", {"flow": {}, "msg": {}})  # default render = 30d
        flowmap = astats.get("flow", {})
        msgmap  = astats.get("msg", {})
        cur     = s["currency"]
        for row in auto.get("rows", []):
            st_cls = status_cls(row["status"])
            aid    = row.get("id", "")
            f      = flowmap.get(aid, {})
            sent, orate, crate = f.get("sent"), f.get("openRate"), f.get("clickRate")
            rev, orders        = f.get("revenue"), f.get("orders")
            unsub, spam        = f.get("unsubRate"), f.get("spamRate")
            po     = (orders / sent) if (orders is not None and sent) else None
            msgs   = row.get("messages", [])
            rid    = f"{s['id']}::{aid}"
            nm_esc = html.escape(row["name"], quote=True)
            tg_esc = html.escape(row["trigger"], quote=True)
            caret  = ('<span class="auto-caret" onclick="toggleAuto(this)">▸</span>'
                      if msgs else '<span class="auto-caret-empty"></span>')
            auto_rows_html += f"""
        <tr class="auto-flow" data-store="{s['id']}" data-channel="{row['channels']}" data-rid="{rid}"
            data-name="{nm_esc}" data-status="{row['status']}" data-trigger="{tg_esc}" data-cur="{cur}"
            data-sent="{sent if sent is not None else ''}" data-open="{orate if orate is not None else ''}"
            data-ctr="{crate if crate is not None else ''}" data-po="{po if po is not None else ''}"
            data-rev="{rev if rev is not None else ''}" data-orders="{orders if orders is not None else ''}"
            data-spam="{spam if spam is not None else ''}" data-unsub="{unsub if unsub is not None else ''}">
          <td><div class="store-cell"><span class="dot" style="background:{s['color']}"></span><span>{s['flag']} {s['id']}</span></div></td>
          <td class="camp-name" title="{nm_esc}">{caret}{nm_esc}</td>
          <td><span class="{st_cls}">{row['status']}</span></td>
          <td class="muted small">{tg_esc}</td>
          <td class="num">{fmt_num(sent)}</td>
          <td><span class="heat {open_cls(orate)}">{fmt_pct(orate)}</span></td>
          <td><span class="heat {ctr_cls(crate)}">{fmt_pct(crate)}</span></td>
          <td class="num">{fmt_pct(po)}</td>
          <td class="num fw6">{fmt_rev(rev, cur)}</td>
          <td class="num">{fmt_num(orders)}</td>
          <td class="num muted">{fmt_pct(spam)}</td>
          <td><span class="heat {unsub_cls(unsub)}">{fmt_pct(unsub)}</span></td>
        </tr>"""
            for i, m in enumerate(msgs, 1):
                ms = msgmap.get(m.get("id", ""), {})
                msent, morate, mcrate = ms.get("sent"), ms.get("openRate"), ms.get("clickRate")
                mrev, morders         = ms.get("revenue"), ms.get("orders")
                munsub, mspam         = ms.get("unsubRate"), ms.get("spamRate")
                mpo   = (morders / msent) if (morders is not None and msent) else None
                chn   = m.get("channel", "email")
                bcls, blab = {"email": ("tag-email", "Email"), "sms": ("tag-sms", "SMS"),
                              "push": ("tag-push", "Push")}.get(chn, ("tag-email", chn.upper()))
                mlabel = html.escape(m.get("title") or f"Step {i}", quote=True)
                auto_rows_html += f"""
        <tr class="auto-msg" data-parent="{rid}" data-store="{s['id']}" data-cur="{cur}"
            data-msgid="{m.get('id','')}" data-ch="{blab}" data-label="{mlabel}"
            data-sent="{msent if msent is not None else ''}" data-open="{morate if morate is not None else ''}"
            data-ctr="{mcrate if mcrate is not None else ''}" data-po="{mpo if mpo is not None else ''}"
            data-rev="{mrev if mrev is not None else ''}" data-orders="{morders if morders is not None else ''}"
            data-spam="{mspam if mspam is not None else ''}" data-unsub="{munsub if munsub is not None else ''}" hidden>
          <td></td>
          <td class="auto-msg-label"><span class="tag {bcls}">{blab}</span> {mlabel}</td>
          <td></td><td></td>
          <td class="num">{fmt_num(msent)}</td>
          <td><span class="heat {open_cls(morate)}">{fmt_pct(morate)}</span></td>
          <td><span class="heat {ctr_cls(mcrate)}">{fmt_pct(mcrate)}</span></td>
          <td class="num">{fmt_pct(mpo)}</td>
          <td class="num">{fmt_rev(mrev, cur)}</td>
          <td class="num">{fmt_num(morders)}</td>
          <td class="num muted">{fmt_pct(mspam)}</td>
          <td><span class="heat {unsub_cls(munsub)}">{fmt_pct(munsub)}</span></td>
        </tr>"""

    if not auto_rows_html:
        auto_rows_html = '<tr class="empty-row"><td colspan="12">No automation data available</td></tr>'

    # ────────────────────────────────────────────────────────────────────────
    # VIEW 4 — Form detail table
    # ────────────────────────────────────────────────────────────────────────
    form_rows = ""
    for s in stores:
        for f in s.get("forms", []):
            f_type = f.get("type", "—")
            type_cls = "tag-popup" if "popup" in f_type.lower() else ("tag-embed" if "embed" in f_type.lower() else "tag-email")
            st_cls = status_cls(f.get("status", ""))
            form_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span>{s['flag']} {s['id']}</span>
          </div></td>
          <td class="camp-name" title="{f['name']}">{f['name']}</td>
          <td><span class="tag {type_cls}">{f_type}</span></td>
          <td><span class="{st_cls}">{f.get('status','—')}</span></td>
          <td class="num">{fmt_num(f.get('views'))}</td>
          <td><span class="heat h-gray">{fmt_pct(f.get('interaction_rate'))}</span></td>
          <td><span class="heat h-gray">{fmt_pct(f.get('submit_rate'))}</span></td>
          <td><span class="heat h-gray">{fmt_pct(f.get('signup_rate'))}</span></td>
        </tr>"""

    if not form_rows:
        form_rows = '<tr class="empty-row"><td colspan="8">No form data available</td></tr>'

    # ────────────────────────────────────────────────────────────────────────
    # Assemble HTML
    # ────────────────────────────────────────────────────────────────────────
    store_ids_js = str(store_ids)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Omnisend Dashboard — Giraffe Tools</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, "PingFang SC", sans-serif;
    background: #f0f2f5; color: #1e293b; font-size: 14px; line-height: 1.5;
  }}

  /* ── Topbar ── */
  .topbar {{
    background: #fff; border-bottom: 1px solid #e2e8f0;
    padding: 0 24px; height: 52px;
    display: flex; align-items: center; justify-content: space-between;
    position: sticky; top: 0; z-index: 100;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
  }}
  .topbar-logo {{ font-size: 15px; font-weight: 700; color: #0f172a; }}
  .topbar-logo span {{ color: #2563eb; }}
  .topbar-right {{ font-size: 11px; color: #94a3b8; display:flex; align-items:center; gap:6px; }}
  .live-dot {{ width:6px; height:6px; background:#22c55e; border-radius:50%; display:inline-block; animation:blink 2s infinite; }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}

  /* ── Filter bar ── */
  .filter-bar {{
    background: #fff; border-bottom: 1px solid #e2e8f0;
    padding: 10px 24px; position: sticky; top: 52px; z-index: 99;
    box-shadow: 0 1px 3px rgba(0,0,0,.04);
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  }}
  .filter-label {{ font-size: 11px; color: #94a3b8; font-weight: 700;
    text-transform: uppercase; letter-spacing: .5px; white-space: nowrap; }}
  .filter-group {{ display: flex; align-items: center; gap: 6px; }}
  .filter-group label {{ font-size: 11px; color: #64748b; font-weight: 600; white-space: nowrap; }}
  .filter-select {{
    font-size: 12px; font-weight: 600; color: #0f172a;
    border: 1.5px solid #e2e8f0; border-radius: 8px;
    padding: 5px 28px 5px 10px; background: #fff;
    appearance: none; cursor: pointer;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2394a3b8' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 9px center;
    transition: border-color .15s;
  }}
  .filter-select:focus {{ outline: none; border-color: #2563eb; }}
  .filter-sep {{ width: 1px; height: 20px; background: #e2e8f0; flex-shrink: 0; }}
  .filter-date-badge {{
    font-size: 11px; color: #64748b; background: #f1f5f9;
    padding: 4px 10px; border-radius: 20px; border: 1px solid #e2e8f0; white-space: nowrap;
  }}

  /* Type buttons */
  .type-group {{ display: flex; gap: 4px; }}
  .type-btn {{
    padding: 5px 14px; border-radius: 8px; font-size: 12px; font-weight: 600;
    cursor: pointer; border: 1.5px solid #e2e8f0; background: #fff; color: #64748b;
    transition: all .15s; white-space: nowrap;
  }}
  .type-btn:hover {{ border-color: #94a3b8; color: #0f172a; }}
  .type-btn.active {{ border-color: #2563eb; color: #2563eb; background: #eff6ff; }}

  /* Export button (right side of filter bar) */
  .export-btn {{
    margin-left: auto; padding: 6px 14px; border-radius: 8px;
    font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap;
    border: 1.5px solid #16a34a; color: #fff; background: #16a34a;
    transition: filter .15s, transform .05s;
  }}
  .export-btn:hover {{ filter: brightness(1.07); }}
  .export-btn:active {{ transform: translateY(1px); }}

  /* ── Layout ── */
  .page {{ max-width: 1440px; margin: 0 auto; padding: 20px 20px 60px; }}
  .view {{ display: none; }}
  .view.active {{ display: block; }}

  /* ── Section title ── */
  .section-title {{
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #94a3b8;
    margin: 28px 0 12px;
    display: flex; align-items: center; gap: 10px;
  }}
  .section-title .st-icon {{ font-size: 14px; }}
  .section-title::after {{ content: ''; flex: 1; height: 1px; background: #e2e8f0; }}

  /* ── KPI cards ── */
  .cards-grid {{
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 12px; margin-bottom: 8px;
    transition: all .2s;
  }}
  @media (max-width: 1280px) {{ .cards-grid {{ grid-template-columns: repeat(4,1fr); }} }}
  @media (max-width: 700px)  {{ .cards-grid {{ grid-template-columns: repeat(2,1fr); }} }}
  .cards-grid.single-store {{ grid-template-columns: repeat(3, minmax(0,320px)) !important; }}

  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 16px 14px 12px; transition: box-shadow .15s, transform .15s;
  }}
  .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.07); transform: translateY(-1px); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
  .store-badge {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
  .card-currency {{ font-size: 11px; color: #94a3b8; font-weight: 500; }}
  .card-name {{ font-size: 11px; color: #64748b; margin-bottom: 12px; font-weight: 500; }}
  .card-metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }}
  .m-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: .5px; }}
  .m-value {{ font-size: 15px; font-weight: 700; color: #0f172a; line-height: 1.2; }}
  .card-footer {{
    display: flex; flex-wrap: wrap; gap: 5px;
    border-top: 1px solid #f1f5f9; padding-top: 8px;
  }}
  .card-footer span {{
    font-size: 10px; color: #64748b; background: #f8fafc;
    padding: 2px 6px; border-radius: 4px; border: 1px solid #e2e8f0;
  }}

  /* ── KPI banner (Campaign view) ── */
  .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  @media (max-width: 700px) {{ .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  .kpi-card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 14px 16px; border-top: 3px solid #2563eb;
  }}
  .kpi-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: .6px; font-weight: 700; }}
  .kpi-val {{ font-size: 22px; font-weight: 700; color: #0f172a; line-height: 1.3; margin-top: 2px; }}
  .kpi-sub {{ font-size: 10px; color: #94a3b8; }}

  /* ── Automation summary (unified panel) ── */
  .auto-summary {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; margin-bottom: 16px; }}
  .as-row {{ display: flex; align-items: stretch; border-top: 1px solid #eef2f7; }}
  .as-row:first-child {{ border-top: none; }}
  .as-rowlabel {{
    width: 150px; flex-shrink: 0; display: flex; align-items: center; gap: 6px;
    padding: 14px 16px; font-size: 11px; font-weight: 800; letter-spacing: .6px;
    text-transform: uppercase; color: #475569; background: #f8fafc;
    border-right: 1px solid #eef2f7;
  }}
  .as-grid {{ flex: 1; display: grid; grid-template-columns: repeat(4, 1fr); }}
  .as-item {{ padding: 12px 18px; border-left: 1px solid #f1f5f9; }}
  .as-item:first-child {{ border-left: none; }}
  .as-lab {{ font-size: 10px; font-weight: 700; letter-spacing: .5px; text-transform: uppercase; color: #94a3b8; margin-bottom: 2px; }}
  .as-val {{ font-size: 21px; font-weight: 800; color: #0f172a; line-height: 1.3; }}
  .as-sub {{ font-size: 11px; color: #94a3b8; margin-top: 1px; }}
  @media (max-width: 860px) {{
    .as-row {{ flex-direction: column; }}
    .as-rowlabel {{ width: auto; border-right: none; border-bottom: 1px solid #eef2f7; }}
    .as-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .as-item:nth-child(2) {{ border-left: none; }}
  }}

  /* ── Panels ── */
  .panel {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    overflow: hidden; margin-bottom: 14px;
  }}
  .panel-head {{
    padding: 13px 18px 11px; border-bottom: 1px solid #f1f5f9;
    display: flex; align-items: baseline; gap: 8px;
  }}
  .panel-head-title {{ font-size: 13px; font-weight: 700; color: #0f172a; }}
  .panel-head-sub {{ font-size: 11px; color: #94a3b8; }}

  /* ── Tables ── */
  .table-wrap {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    overflow: hidden; margin-bottom: 14px; overflow-x: auto;
  }}
  table {{ width: 100%; border-collapse: collapse; min-width: 700px; }}
  thead th {{
    background: #f8fafc; text-align: left;
    padding: 9px 12px; font-size: 10px; font-weight: 700;
    color: #64748b; text-transform: uppercase; letter-spacing: .6px;
    border-bottom: 1px solid #e2e8f0; white-space: nowrap;
  }}
  thead th.num {{ text-align: right; }}
  tbody td {{ padding: 10px 12px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #fafbfc; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #94a3b8; }}
  .small {{ font-size: 12px; }}
  .fw6 {{ font-weight: 600; }}
  .pos {{ color: #16a34a; font-weight: 600; }}
  .neg {{ color: #dc2626; font-weight: 500; }}
  .divider-col {{ width: 1px; background: #e2e8f0; padding: 0; }}
  thead th.divider-col {{ background: #e2e8f0; }}

  /* ── Store cell ── */
  .store-cell {{ display: flex; align-items: center; gap: 7px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}

  /* ── Heat badges ── */
  .heat {{ display: inline-block; padding: 2px 7px; border-radius: 5px; font-size: 12px; font-weight: 600; }}
  .h-green  {{ background: #dcfce7; color: #15803d; }}
  .h-yellow {{ background: #fef9c3; color: #a16207; }}
  .h-red    {{ background: #fee2e2; color: #b91c1c; }}
  .h-gray   {{ background: #f1f5f9; color: #64748b; }}

  /* ── Tags ── */
  .tag {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; white-space: nowrap; }}
  .tag-email {{ background: #dbeafe; color: #1d4ed8; }}
  .tag-sms   {{ background: #dcfce7; color: #15803d; }}
  .tag-push  {{ background: #ede9fe; color: #7c3aed; }}
  .tag-auto  {{ background: #fff7ed; color: #c2410c; }}
  .tag-popup {{ background: #fdf4ff; color: #a21caf; }}
  .tag-embed {{ background: #f0fdf4; color: #15803d; }}

  /* ── Status text ── */
  .status-on   {{ font-size: 11px; font-weight: 700; color: #16a34a; }}
  .status-off  {{ font-size: 11px; font-weight: 600; color: #94a3b8; }}
  .status-draft {{ font-size: 11px; font-weight: 600; color: #d97706; }}

  /* ── Progress rows ── */
  .prog-row {{
    display: flex; align-items: center; gap: 10px;
    padding: 9px 18px; border-bottom: 1px solid #f8fafc;
  }}
  .prog-row:last-child {{ border-bottom: none; }}
  .prog-label {{ width: 86px; flex-shrink: 0; font-size: 12px; font-weight: 700; }}
  .prog-track {{ flex: 1; height: 7px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }}
  .prog-fill  {{ height: 100%; border-radius: 4px; }}
  .prog-count {{ width: 40px; text-align: right; font-size: 12px; color: #64748b; flex-shrink: 0; }}
  .prog-meta  {{ display: flex; align-items: center; gap: 5px; flex-shrink: 0; }}

  /* ── Category rows ── */
  .cat-row {{
    display: flex; align-items: center; gap: 8px;
    padding: 7px 18px; border-bottom: 1px solid #f8fafc;
  }}
  .cat-row:last-child {{ border-bottom: none; }}
  .cat-label {{ width: 160px; flex-shrink: 0; font-size: 12px; color: #374151; font-weight: 500; }}
  .cat-count {{ width: 90px; text-align: right; font-size: 11px; color: #64748b; flex-shrink: 0; }}

  /* ── Pills ── */
  .pill {{ font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 10px; flex-shrink: 0; }}
  .pill-green {{ background: #dcfce7; color: #16a34a; }}
  .pill-gray  {{ background: #f1f5f9; color: #64748b; }}
  .pill-dim   {{ background: #fef9c3; color: #92400e; }}

  /* ── Two-col ── */
  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }}
  @media (max-width: 860px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  /* ── Channel stat strip ── */
  .ch-stat {{ display: flex; gap: 12px; padding: 10px 18px; border-top: 1px solid #f1f5f9; }}
  .ch-item {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: #64748b; }}
  .ch-dot  {{ width: 8px; height: 8px; border-radius: 50%; }}

  /* ── Camp name ellipsis ── */
  .camp-name {{ font-weight: 500; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  /* ── Automation drill-down ── */
  .auto-flow {{ cursor: default; }}
  .auto-caret {{
    display: inline-block; width: 14px; cursor: pointer; color: #94a3b8;
    font-size: 10px; user-select: none; transition: color .15s;
  }}
  .auto-caret:hover {{ color: #2563eb; }}
  .auto-caret-empty {{ display: inline-block; width: 14px; }}
  tr.auto-msg td {{ background: #fbfcfe; font-size: 12px; }}
  tr.auto-msg:hover td {{ background: #f5f8ff; }}
  .auto-msg-label {{ color: #475569; padding-left: 18px !important; }}

  /* ── Legend ── */
  .legend {{ display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; font-size: 11px; color: #64748b; }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}

  /* ── Empty / scroll offset ── */
  .anchor {{ scroll-margin-top: 110px; }}
  .empty-row td {{ text-align: center; color: #94a3b8; padding: 24px; font-size: 12px; }}

  /* ── Footer ── */
  .footer {{ margin-top: 48px; padding: 18px 0 0; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8; }}
</style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
  <div class="topbar-logo">Omnisend <span>Dashboard</span></div>
  <div class="topbar-right">
    <span class="live-dot"></span>
    Updated weekly &nbsp;·&nbsp; {updated_at}
  </div>
</div>

<!-- FILTER BAR -->
<div class="filter-bar">
  <span class="filter-label">筛选</span>

  <div class="filter-group">
    <label>📅 时间</label>
    <div class="type-group">
      <button class="type-btn" data-range="7"  onclick="setRange('7')" id="rbtn-7">近7天</button>
      <button class="type-btn active" data-range="30" onclick="setRange('30')" id="rbtn-30">近30天</button>
      <button class="type-btn" data-range="custom" onclick="setRange('custom')" id="rbtn-custom">自定义</button>
    </div>
    <div id="custom-range-wrap" style="display:none;align-items:center;gap:4px">
      <input type="date" class="filter-select" id="custom-from" min="{range_min}" max="{range_max}" value="{range_min}" style="padding:4px 8px" onchange="applyCustomRange()">
      <span style="color:#94a3b8;font-size:12px">–</span>
      <input type="date" class="filter-select" id="custom-to" min="{range_min}" max="{range_max}" value="{range_max}" style="padding:4px 8px" onchange="applyCustomRange()">
    </div>
    <span class="filter-date-badge" id="date-badge">{display_30}</span>
  </div>

  <div class="filter-sep"></div>

  <div class="filter-group">
    <label>Market</label>
    <select class="filter-select" id="sel-market" onchange="applyFilters()">
      {market_opts}    </select>
  </div>

  <div class="filter-group">
    <label>Channel</label>
    <select class="filter-select" id="sel-channel" onchange="applyFilters()">
      <option value="all">All Channels</option>
      <option value="EDM">📧 EDM</option>
      <option value="SMS">💬 SMS</option>
      <option value="Push">🔔 Push</option>
    </select>
  </div>

  <div class="filter-sep"></div>

  <div class="filter-group">
    <label>View</label>
    <div class="type-group">
      <button class="type-btn active" data-type="overview"  onclick="setType('overview')">📊 Overview</button>
      <button class="type-btn"        data-type="campaign"  onclick="setType('campaign')">📧 Campaign</button>
      <button class="type-btn"        data-type="automation" onclick="setType('automation')">⚡ Automation</button>
      <button class="type-btn"        data-type="form"      onclick="setType('form')">📋 Form</button>
    </div>
  </div>

  <button class="export-btn" id="export-btn" onclick="exportCSV()" title="导出当前时间段的所有面板数据为 CSV">⬇ 导出数据</button>
</div>

<div class="page">

<!-- ═══════════════════════════════════════════════════════════════
     VIEW: OVERVIEW
═══════════════════════════════════════════════════════════════ -->
<div id="view-overview" class="view active">

  <div class="section-title"><span class="st-icon">🏪</span> Store Overview — Last 30 Days
    <span id="ov-custom-note" style="display:none;font-weight:400;color:#94a3b8;text-transform:none;letter-spacing:0;font-size:11px">· 总览按近30天显示；自定义区间应用于 Campaign 视图</span>
  </div>
  <div class="cards-grid" id="cards-grid">
{cards_html}
  </div>

  <div class="section-title"><span class="st-icon">📊</span> Email Performance Analytics</div>
  <div class="legend">
    <div class="legend-item"><span class="heat h-green" style="font-size:10px">●</span> Open ≥45% · CTR ≥2.5% · Unsub ≤0.4%</div>
    <div class="legend-item"><span class="heat h-yellow" style="font-size:10px">●</span> Moderate</div>
    <div class="legend-item"><span class="heat h-red" style="font-size:10px">●</span> Needs attention</div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Store</th>
          <th class="num">Sent</th>
          <th>Open Rate</th>
          <th>CTR</th>
          <th class="num">Attributed Rev.</th>
          <th class="num">Total Rev.</th>
          <th class="num">Orders</th>
          <th>Unsub Rate</th>
        </tr>
      </thead>
      <tbody id="analytics-tbody">{analytics_rows}</tbody>
    </table>
  </div>

  <div class="section-title"><span class="st-icon">📧</span> Campaign vs Automation</div>
  <div class="panel">
    <div class="panel-head">
      <span class="panel-head-title">Performance Split by Source</span>
      <span class="panel-head-sub">Last 30 days</span>
    </div>
    <table>
      <thead>
        <tr>
          <th rowspan="2">Store</th>
          <th class="num" colspan="4" style="border-bottom:1px solid #2563eb22;color:#2563eb">📧 Campaigns</th>
          <th class="divider-col" rowspan="2"></th>
          <th class="num" colspan="4" style="border-bottom:1px solid #7c3aed22;color:#7c3aed">⚡ Automations</th>
        </tr>
        <tr>
          <th class="num">Sent</th><th>Open%</th><th class="num">Revenue</th><th class="num">Orders</th>
          <th class="divider-col" style="display:none"></th>
          <th class="num">Sent</th><th>Open%</th><th class="num">Revenue</th><th class="num">Orders</th>
        </tr>
      </thead>
      <tbody id="split-tbody">{split_rows}</tbody>
    </table>
  </div>

  <div class="section-title"><span class="st-icon">🌱</span> Subscriber Growth <span style="font-size:11px;font-weight:400;color:#94a3b8;text-transform:none;letter-spacing:0">— last 30 days</span></div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Store</th>
          <th class="num">New Email Subs</th>
          <th class="num">Email Unsubs</th>
          <th>Net Growth</th>
          <th class="num">New SMS Subs</th>
        </tr>
      </thead>
      <tbody id="growth-tbody">{growth_rows}</tbody>
    </table>
  </div>

  <div class="section-title"><span class="st-icon">🎯</span> Segment Coverage</div>
  <div class="panel" id="seg-panel">
    <div class="panel-head">
      <span class="panel-head-title">Configured Segments per Store</span>
    </div>
{seg_rows}
  </div>

</div><!-- /view-overview -->


<!-- ═══════════════════════════════════════════════════════════════
     VIEW: CAMPAIGN
═══════════════════════════════════════════════════════════════ -->
<div id="view-campaign" class="view">

  <!-- Campaign aggregate stats (date-switchable via JS) -->
  <div class="kpi-grid" id="camp-kpi-grid" style="margin-bottom:18px"></div>

  <div class="section-title"><span class="st-icon">📧</span> Recent Campaigns</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Campaign / Subject</th>
          <th>Channel</th>
          <th>Send Date</th>
          <th>Status</th>
          <th class="num">Sent</th>
          <th>CTR</th>
          <th>Open%</th>
          <th class="num">Opens</th>
          <th class="num">Clicks</th>
          <th class="num">Revenue</th>
          <th class="num">Orders</th>
          <th>Unsub%</th>
        </tr>
      </thead>
      <tbody id="camp-tbody">{camp_rows}</tbody>
    </table>
  </div>

</div><!-- /view-campaign -->


<!-- ═══════════════════════════════════════════════════════════════
     VIEW: AUTOMATION
═══════════════════════════════════════════════════════════════ -->
<div id="view-automation" class="view">

  <div class="section-title"><span class="st-icon">📈</span> Automation Summary
    <span id="au-custom-note" style="display:none;font-weight:400;color:#94a3b8;text-transform:none;letter-spacing:0;font-size:11px">· 汇总按近30天显示（自定义区间应用于下方明细）</span>
  </div>
  <div class="auto-summary">
    <div class="as-row">
      <div class="as-rowlabel">💰 Sales</div>
      <div class="as-grid">
        <div class="as-item"><div class="as-lab">Revenue</div><div class="as-val" id="au-revenue">—</div><div class="as-sub">Attributed</div></div>
        <div class="as-item"><div class="as-lab">Placed orders</div><div class="as-val" id="au-orders">—</div><div class="as-sub">Attributed</div></div>
        <div class="as-item"><div class="as-lab">Revenue / order</div><div class="as-val" id="au-rpo">—</div></div>
        <div class="as-item"><div class="as-lab">Revenue / message</div><div class="as-val" id="au-rpm">—</div></div>
      </div>
    </div>
    <div class="as-row">
      <div class="as-rowlabel">📨 Engagement</div>
      <div class="as-grid">
        <div class="as-item"><div class="as-lab">Messages sent</div><div class="as-val" id="au-sent">—</div></div>
        <div class="as-item"><div class="as-lab">Open rate</div><div class="as-val" id="au-open">—</div><div class="as-sub" id="au-open-sub"></div></div>
        <div class="as-item"><div class="as-lab">Click rate</div><div class="as-val" id="au-click">—</div><div class="as-sub" id="au-click-sub"></div></div>
        <div class="as-item"><div class="as-lab">Placed order rate</div><div class="as-val" id="au-por">—</div><div class="as-sub" id="au-por-sub"></div></div>
      </div>
    </div>
    <div class="as-row">
      <div class="as-rowlabel">📬 Deliverability</div>
      <div class="as-grid">
        <div class="as-item"><div class="as-lab">Messages sent</div><div class="as-val" id="au-sent2">—</div></div>
        <div class="as-item"><div class="as-lab">Marked as spam</div><div class="as-val" id="au-spam">—</div></div>
        <div class="as-item"><div class="as-lab">Unsubscribe rate</div><div class="as-val" id="au-unsub">—</div></div>
        <div class="as-item"><div class="as-lab">Failed delivery</div><div class="as-val" style="color:#cbd5e1;font-size:16px">N/A</div><div class="as-sub">API 未提供</div></div>
      </div>
    </div>
  </div>

  <div class="section-title"><span class="st-icon">⚡</span> Workflow Performance
    <span style="font-weight:400;color:#94a3b8;text-transform:none;letter-spacing:0;font-size:11px">— 点击流程名称展开查看每条 Email / SMS 消息</span>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Automation / Message</th>
          <th>Status</th>
          <th>Trigger</th>
          <th class="num">Sent</th>
          <th>Open%</th>
          <th>Click%</th>
          <th class="num">Placed Order%</th>
          <th class="num">Revenue</th>
          <th class="num">Orders</th>
          <th>Spam%</th>
          <th>Unsub%</th>
        </tr>
      </thead>
      <tbody id="auto-tbody">{auto_rows_html}</tbody>
    </table>
  </div>

</div><!-- /view-automation -->


<!-- ═══════════════════════════════════════════════════════════════
     VIEW: FORM
═══════════════════════════════════════════════════════════════ -->
<div id="view-form" class="view">

  <div class="section-title"><span class="st-icon">📋</span> Signup Forms</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Form Name</th>
          <th>Type</th>
          <th>Status</th>
          <th class="num">Views</th>
          <th>Interaction%</th>
          <th>Submit%</th>
          <th>Signup%</th>
        </tr>
      </thead>
      <tbody id="form-tbody">{form_rows}</tbody>
    </table>
  </div>

</div><!-- /view-form -->


  <!-- FOOTER -->
  <div class="footer">
    <div>Omnisend Multi-Store · 7 brands · Giraffe Tools &amp; Gitryin US</div>
    <div>Auto-refreshes every Monday 08:00 UTC · {updated_at}</div>
  </div>

</div><!-- /page -->

<script>
const STORE_IDS  = {store_ids_js};
const DATA_30    = {data_30_json};
const DATA_7     = {data_7_json};
const AUTO_30    = {auto_30_json};
const AUTO_7     = {auto_7_json};
const DISPLAY_30 = "{display_30}";
const DISPLAY_7  = "{display_7}";
const RANGE_MIN  = "{range_min}";
const RANGE_MAX  = "{range_max}";

let currentType  = 'overview';
let currentRange = '30';
let customFrom   = RANGE_MIN;
let customTo     = RANGE_MAX;

// ── Formatters (mirror Python) ───────────────────────────────────────────────
function fmtNum(n) {{
  if (n == null) return '—';
  return Math.round(n).toLocaleString();
}}
function fmtPct(n) {{
  if (n == null) return '—';
  return (n * 100).toFixed(2) + '%';
}}
function fmtRev(n, cur) {{
  if (n == null) return '—';
  const syms = {{USD:'$',CAD:'CA$',GBP:'£',AUD:'A$',EUR:'€',JPY:'¥'}};
  const sym = syms[cur] || cur + ' ';
  const val = cur === 'JPY' ? Math.round(n).toLocaleString() : Math.round(n).toLocaleString();
  return sym + val;
}}
function fmtMoney2(n, cur) {{  // money with 2 decimals (per-order / per-message)
  if (n == null) return '—';
  const syms = {{USD:'$',CAD:'CA$',GBP:'£',AUD:'A$',EUR:'€',JPY:'¥'}};
  const sym = syms[cur] || cur + ' ';
  return sym + Number(n).toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
}}
function openCls(r) {{
  if (r == null) return 'h-gray';
  const p = r * 100;
  return p >= 45 ? 'h-green' : p >= 35 ? 'h-yellow' : 'h-red';
}}
function ctrCls(r) {{
  if (r == null) return 'h-gray';
  const p = r * 100;
  return p >= 2.5 ? 'h-green' : p >= 1.5 ? 'h-yellow' : 'h-red';
}}
function unsubCls(r) {{
  if (r == null) return 'h-gray';
  const p = r * 100;
  return p <= 0.4 ? 'h-green' : p <= 0.7 ? 'h-yellow' : 'h-red';
}}
function growthCls(net) {{
  if (net == null) return 'h-gray';
  return net > 0 ? 'h-green' : net < 0 ? 'h-red' : 'h-gray';
}}
function heat(cls, txt) {{ return `<span class="heat ${{cls}}">${{txt}}</span>`; }}

// ── Range data resolution ─────────────────────────────────────────────────────
// The Overview aggregates (all-channel totals incl. automations) are only
// available from Omnisend for the 7d / 30d windows. A custom range drives the
// Campaign view (filtered by send date); the Overview falls back to 30d and
// shows a note so the numbers are never mislabelled.
function rangeData(sid) {{
  if (currentRange === '7') return DATA_7[sid];
  return DATA_30[sid];
}}

// ── Date range switching ──────────────────────────────────────────────────────
function updateBadge() {{
  const badge = document.getElementById('date-badge');
  if (!badge) return;
  if (currentRange === '7')       badge.textContent = DISPLAY_7;
  else if (currentRange === '30') badge.textContent = DISPLAY_30;
  else                            badge.textContent = customFrom + ' – ' + customTo;
  const note = document.getElementById('ov-custom-note');
  if (note) note.style.display = (currentRange === 'custom') ? 'inline' : 'none';
  const anote = document.getElementById('au-custom-note');
  if (anote) anote.style.display = (currentRange === 'custom') ? 'inline' : 'none';
}}

// ── Automation summary panels (Sales / Engagement / Deliverability) ───────────
function updateAutoPanels() {{
  const data   = currentRange === '7' ? DATA_7 : DATA_30;  // custom → 30d
  const market = document.getElementById('sel-market').value;
  const ids    = market === 'all' ? STORE_IDS : [market];
  let sent = 0, rev = 0, orders = 0, opens = 0, clicks = 0, spamN = 0, unsubN = 0;
  const curSet = new Set();
  ids.forEach(sid => {{
    const d = data[sid]; if (!d) return;
    sent   += d.autoSent   || 0;
    rev    += d.autoRev    || 0;
    orders += d.autoOrders || 0;
    opens  += d.autoOpens  || 0;
    clicks += d.autoClicks || 0;
    if (d.autoSpam  != null && d.autoSent) spamN  += d.autoSpam  * d.autoSent;
    if (d.autoUnsub != null && d.autoSent) unsubN += d.autoUnsub * d.autoSent;
    if (d.autoRev) curSet.add(d.currency);
  }});
  const cur    = curSet.size === 1 ? [...curSet][0] : 'USD';
  const openR  = sent ? opens / sent  : null;
  const clickR = sent ? clicks / sent : null;
  const por    = sent ? orders / sent : null;
  const spamR  = sent ? spamN / sent  : null;
  const unsubR = sent ? unsubN / sent : null;
  const set = (id, v) => {{ const e = document.getElementById(id); if (e) e.textContent = v; }};
  set('au-revenue', fmtRev(rev, cur));
  set('au-orders',  fmtNum(orders));
  set('au-rpo',     orders ? fmtMoney2(rev / orders, cur) : '—');
  set('au-rpm',     sent   ? fmtMoney2(rev / sent, cur)   : '—');
  set('au-sent',    fmtNum(sent));
  set('au-sent2',   fmtNum(sent));
  set('au-open',    fmtPct(openR));   set('au-open-sub',  fmtNum(opens)  + ' opens');
  set('au-click',   fmtPct(clickR));  set('au-click-sub', fmtNum(clicks) + ' clicks');
  set('au-por',     fmtPct(por));     set('au-por-sub',   fmtNum(orders) + ' orders');
  set('au-spam',    fmtPct(spamR));
  set('au-unsub',   fmtPct(unsubR));
}}

function setRange(r) {{
  currentRange = r;
  document.querySelectorAll('[data-range]').forEach(b =>
    b.classList.toggle('active', b.dataset.range === r));
  const wrap = document.getElementById('custom-range-wrap');
  if (wrap) wrap.style.display = (r === 'custom') ? 'flex' : 'none';
  updateBadge();
  updateCampDateFilter();
  updateOverviewData();
  updateCampKpis();
  updateAutoPanels();
  updateAutoTable();
  applyFilters();
}}

// ── Workflow Performance table: swap per-flow & per-message values by range ────
function autoStatsFor() {{ return currentRange === '7' ? AUTO_7 : AUTO_30; }}  // custom → 30d

function fillAutoRow(r, st, cur) {{
  const sent = st.sent, orate = st.openRate, crate = st.clickRate;
  const rev = st.revenue, orders = st.orders, unsub = st.unsubRate, spam = st.spamRate;
  const po = (orders != null && sent) ? orders / sent : null;
  const c = r.querySelectorAll('td');
  if (c.length < 12) return;
  c[4].textContent  = fmtNum(sent);
  c[5].innerHTML    = heat(openCls(orate), fmtPct(orate));
  c[6].innerHTML    = heat(ctrCls(crate), fmtPct(crate));
  c[7].textContent  = fmtPct(po);
  c[8].textContent  = fmtRev(rev, cur);
  c[9].textContent  = fmtNum(orders);
  c[10].textContent = fmtPct(spam);
  c[11].innerHTML   = heat(unsubCls(unsub), fmtPct(unsub));
  const d = r.dataset;
  d.sent = sent ?? ''; d.open = orate ?? ''; d.ctr = crate ?? ''; d.po = po ?? '';
  d.rev = rev ?? ''; d.orders = orders ?? ''; d.spam = spam ?? ''; d.unsub = unsub ?? '';
}}

function updateAutoTable() {{
  const A = autoStatsFor();
  document.querySelectorAll('#auto-tbody tr.auto-flow').forEach(r => {{
    const rid = r.dataset.rid || '';
    const sep = rid.indexOf('::');
    const store = rid.slice(0, sep), aid = rid.slice(sep + 2);
    const st = (A[store] && A[store].flow[aid]) || {{}};
    fillAutoRow(r, st, r.dataset.cur);
  }});
  document.querySelectorAll('#auto-tbody tr.auto-msg').forEach(r => {{
    const st = (A[r.dataset.store] && A[r.dataset.store].msg[r.dataset.msgid]) || {{}};
    fillAutoRow(r, st, r.dataset.cur);
  }});
}}

function applyCustomRange() {{
  const f = document.getElementById('custom-from').value;
  const t = document.getElementById('custom-to').value;
  if (f) customFrom = f;
  if (t) customTo = t;
  if (customFrom > customTo) {{ const tmp = customFrom; customFrom = customTo; customTo = tmp; }}
  setRange('custom');
}}

function updateOverviewData() {{
  STORE_IDS.forEach(sid => {{
    const d = rangeData(sid);
    if (!d) return;
    const cur = d.currency;
    const el = id => document.getElementById(id);
    // Cards
    if (el('val-sent-' + sid))   el('val-sent-' + sid).textContent   = fmtNum(d.sent);
    if (el('val-open-' + sid))   el('val-open-' + sid).textContent   = fmtPct(d.openRate);
    if (el('val-ctr-' + sid))    el('val-ctr-' + sid).textContent    = fmtPct(d.clickRate);
    if (el('val-rev-' + sid))    el('val-rev-' + sid).textContent    = fmtRev(d.revenue, cur);
    if (el('val-orders-' + sid)) el('val-orders-' + sid).textContent = '📦 ' + fmtNum(d.orders) + ' orders';
    // Analytics table
    if (el('tbl-sent-' + sid))   el('tbl-sent-' + sid).textContent   = fmtNum(d.sent);
    if (el('tbl-open-' + sid))   el('tbl-open-' + sid).innerHTML     = heat(openCls(d.openRate), fmtPct(d.openRate));
    if (el('tbl-ctr-' + sid))    el('tbl-ctr-' + sid).innerHTML      = heat(ctrCls(d.clickRate), fmtPct(d.clickRate));
    if (el('tbl-rev-' + sid))    el('tbl-rev-' + sid).textContent    = fmtRev(d.revenue, cur);
    if (el('tbl-trev-' + sid))   el('tbl-trev-' + sid).textContent   = fmtRev(d.totalRev, cur);
    if (el('tbl-orders-' + sid)) el('tbl-orders-' + sid).textContent = fmtNum(d.orders);
    if (el('tbl-unsub-' + sid))  el('tbl-unsub-' + sid).innerHTML    = heat(unsubCls(d.unsubRate), fmtPct(d.unsubRate));
    // Split table (per-source split not available at daily granularity → show 30d)
    const spd = (currentRange === 'custom') ? (DATA_30[sid] || {{}}) : d;
    const spcur = spd.currency || cur;
    if (el('sp-csent-' + sid))   el('sp-csent-' + sid).textContent   = fmtNum(spd.campSent);
    if (el('sp-copen-' + sid))   el('sp-copen-' + sid).innerHTML     = heat(openCls(spd.campOpen), fmtPct(spd.campOpen));
    if (el('sp-crev-' + sid))    el('sp-crev-' + sid).textContent    = fmtRev(spd.campRev, spcur);
    if (el('sp-corders-' + sid)) el('sp-corders-' + sid).textContent = fmtNum(spd.campOrders);
    if (el('sp-asent-' + sid))   el('sp-asent-' + sid).textContent   = fmtNum(spd.autoSent);
    if (el('sp-aopen-' + sid))   el('sp-aopen-' + sid).innerHTML     = heat(openCls(spd.autoOpen), fmtPct(spd.autoOpen));
    if (el('sp-arev-' + sid))    el('sp-arev-' + sid).textContent    = fmtRev(spd.autoRev, spcur);
    if (el('sp-aorders-' + sid)) el('sp-aorders-' + sid).textContent = fmtNum(spd.autoOrders);
    // Growth table
    if (el('gr-sub-' + sid))     el('gr-sub-' + sid).textContent     = fmtNum(d.subEmail);
    if (el('gr-uns-' + sid))     el('gr-uns-' + sid).textContent     = '−' + fmtNum(d.unsubEmail);
    if (el('gr-net-' + sid))     el('gr-net-' + sid).innerHTML       = heat(growthCls(d.netGrowth), (d.netGrowth > 0 ? '+' : '') + fmtNum(d.netGrowth));
    if (el('gr-sms-' + sid))     el('gr-sms-' + sid).textContent     = d.subSms ? fmtNum(d.subSms) : '—';
  }});
}}

// ── Campaign KPI summary banner — aggregated from the visible (in-range) rows ──
function updateCampKpis() {{
  const market  = document.getElementById('sel-market').value;
  const channel = document.getElementById('sel-channel').value;
  let sent = 0, opens = 0, clicks = 0, rev = 0, orders = 0;
  const curSet = new Set();
  const num = v => (v === '' || v == null) ? 0 : parseFloat(v);
  document.querySelectorAll('#camp-tbody tr[data-store]').forEach(row => {{
    if (row.dataset.inRange === '0') return;
    if (market !== 'all' && row.dataset.store !== market) return;
    if (channel !== 'all' && !((row.dataset.channel || '').includes(channel))) return;
    sent   += num(row.dataset.sent);
    opens  += num(row.dataset.opens);
    clicks += num(row.dataset.clicks);
    rev    += num(row.dataset.rev);
    orders += num(row.dataset.orders);
    if (row.dataset.cur && num(row.dataset.rev)) curSet.add(row.dataset.cur);
  }});
  const avgOpen = sent ? opens / sent : null;
  const mixed = curSet.size > 1;
  const cur = curSet.size === 1 ? [...curSet][0] : 'USD';
  const revSub = mixed ? 'Attributed · mixed currencies' : 'Attributed';
  const grid = document.getElementById('camp-kpi-grid');
  if (!grid) return;
  grid.innerHTML = `
    <div class="kpi-card"><div class="kpi-label">CAMPAIGN SENT</div><div class="kpi-val">${{fmtNum(sent)}}</div><div class="kpi-sub">${{fmtNum(clicks)}} clicks</div></div>
    <div class="kpi-card"><div class="kpi-label">AVG OPEN RATE</div><div class="kpi-val">${{fmtPct(avgOpen)}}</div><div class="kpi-sub">${{fmtNum(opens)}} opens</div></div>
    <div class="kpi-card"><div class="kpi-label">CAMPAIGN REVENUE</div><div class="kpi-val">${{fmtRev(rev, cur)}}</div><div class="kpi-sub">${{revSub}}</div></div>
    <div class="kpi-card"><div class="kpi-label">CAMPAIGN ORDERS</div><div class="kpi-val">${{fmtNum(orders)}}</div><div class="kpi-sub">Attributed</div></div>
  `;
}}

// ── Campaign date filter (marks rows in/out of the active range by send date) ──
function updateCampDateFilter() {{
  const now = new Date();
  let fromT, toT;
  if (currentRange === 'custom') {{
    fromT = new Date(customFrom + 'T00:00:00Z');
    toT   = new Date(customTo   + 'T23:59:59Z');
  }} else {{
    const cutoff = currentRange === '7' ? 7 : 30;
    fromT = new Date(now.getTime() - cutoff * 86400000);
    toT   = now;
  }}
  document.querySelectorAll('#camp-tbody tr[data-store]').forEach(row => {{
    const dateStr = row.dataset.sentAt;
    if (!dateStr) {{ row.dataset.inRange = '1'; return; }}
    const sent = new Date(dateStr);
    row.dataset.inRange = (sent >= fromT && sent <= toT) ? '1' : '0';
  }});
}}

// ── View switching ────────────────────────────────────────────────────────────
function setType(t) {{
  currentType = t;
  document.querySelectorAll('.type-btn[data-type]').forEach(b =>
    b.classList.toggle('active', b.dataset.type === t));
  document.querySelectorAll('.view').forEach(v =>
    v.classList.toggle('active', v.id === 'view-' + t));
  applyFilters();
}}

// ── Main filter function ──────────────────────────────────────────────────────
function applyFilters() {{
  const market  = document.getElementById('sel-market').value;
  const channel = document.getElementById('sel-channel').value;

  // ── Overview: KPI cards ──
  const cards = document.querySelectorAll('#cards-grid .card[data-store]');
  let visibleCards = 0;
  cards.forEach(el => {{
    const show = market === 'all' || el.dataset.store === market;
    el.hidden = !show;
    if (show) visibleCards++;
  }});
  document.getElementById('cards-grid')
    .classList.toggle('single-store', visibleCards === 1);

  // ── Overview: table rows (store-only filter) ──
  ['analytics-tbody', 'split-tbody', 'growth-tbody'].forEach(id => {{
    const tbody = document.getElementById(id);
    if (!tbody) return;
    tbody.querySelectorAll('tr[data-store]').forEach(row => {{
      row.hidden = market !== 'all' && row.dataset.store !== market;
    }});
  }});

  // Segment bars
  document.querySelectorAll('#seg-panel .prog-row[data-store]').forEach(el => {{
    el.hidden = market !== 'all' && el.dataset.store !== market;
  }});

  // ── Automation health panels ──
  document.querySelectorAll('#view-automation .prog-row[data-store]').forEach(el => {{
    el.hidden = market !== 'all' && el.dataset.store !== market;
  }});
  document.querySelectorAll('[data-ch]').forEach(el => {{
    el.hidden = el.dataset.ch !== (market === 'all' ? 'all' : market);
  }});
  document.querySelectorAll('.cat-row[data-store]').forEach(el => {{
    el.hidden = market === 'all'
      ? el.dataset.store !== 'GT-US'
      : el.dataset.store !== market;
  }});
  const catTitle = document.getElementById('cat-panel-title');
  if (catTitle) catTitle.textContent =
    market === 'all' ? 'Flow Categories — GT-US' : 'Flow Categories — ' + market;

  // ── Campaign KPI banner + Automation summary panels ──
  updateCampKpis();
  updateAutoPanels();

  // ── Campaign rows (market + channel + date range) ──
  filterDetailTable('camp-tbody', market, channel, true);

  // ── Automation rows (market + channel; keeps drill-down state) ──
  filterAutoTable(market, channel);

  // ── Form rows (market only) ──
  filterDetailTable('form-tbody', market, 'all', false);
}}

function filterDetailTable(tbodyId, market, channel, checkDateRange) {{
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  let anyVisible = false;
  tbody.querySelectorAll('tr[data-store]').forEach(row => {{
    const mOk  = market  === 'all' || row.dataset.store === market;
    const chOk = channel === 'all' || (row.dataset.channel && row.dataset.channel.includes(channel));
    const dOk  = !checkDateRange || row.dataset.inRange !== '0';
    row.hidden = !(mOk && chOk && dOk);
    if (!row.hidden) anyVisible = true;
  }});
  const empty = tbody.querySelector('tr.empty-row');
  if (empty) empty.hidden = anyVisible;
}}

// ── Automation table: flow rows + expandable Email/SMS message sub-rows ────────
function toggleAuto(el) {{
  const tr  = el.closest('tr');
  const rid = tr.dataset.rid;
  const exp = tr.classList.toggle('expanded');
  el.textContent = exp ? '▾' : '▸';
  document.querySelectorAll('#auto-tbody tr.auto-msg').forEach(r => {{
    if (r.dataset.parent === rid) r.hidden = !(exp && !tr.hidden);
  }});
}}

function filterAutoTable(market, channel) {{
  const tbody = document.getElementById('auto-tbody');
  if (!tbody) return;
  const flowVisExp = {{}};
  let anyVisible = false;
  tbody.querySelectorAll('tr.auto-flow').forEach(r => {{
    const mOk  = market  === 'all' || r.dataset.store === market;
    const chOk = channel === 'all' || (r.dataset.channel && r.dataset.channel.includes(channel));
    const vis  = mOk && chOk;
    r.hidden = !vis;
    if (vis) anyVisible = true;
    flowVisExp[r.dataset.rid] = vis && r.classList.contains('expanded');
  }});
  tbody.querySelectorAll('tr.auto-msg').forEach(r => {{
    r.hidden = !flowVisExp[r.dataset.parent];
  }});
  const empty = tbody.querySelector('tr.empty-row');
  if (empty) empty.hidden = anyVisible;
}}

// ── Export all panel data for the selected time range as CSV ──────────────────
function csvEscape(v) {{
  v = (v === null || v === undefined) ? '' : String(v);
  return /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
}}

function exportCSV() {{
  const market  = document.getElementById('sel-market').value;
  const channel = document.getElementById('sel-channel').value;
  const scope   = (market === 'all') ? STORE_IDS : [market];
  const pct = x => (x == null || x === '') ? '' : (Number(x) * 100).toFixed(2) + '%';
  const rangeLabel = (currentRange === '7') ? DISPLAY_7
                   : (currentRange === '30') ? DISPLAY_30
                   : (customFrom + ' to ' + customTo);
  const custom = currentRange === 'custom';
  const ovSuffix = custom ? ' (last 30 days)' : '';

  const lines = [];
  const L = arr => lines.push(arr.map(csvEscape).join(','));

  L(['Omnisend Dashboard — Data Export']);
  L(['Date range', rangeLabel]);
  L(['Market', market === 'all' ? 'All Markets' : market]);
  L(['Channel', channel === 'all' ? 'All Channels' : channel]);
  L(['Generated at', new Date().toISOString()]);
  if (custom) L(['Note', 'Campaigns reflect the selected custom range; Store Overview / Split / Growth reflect the last 30 days (per-period aggregates are only published by Omnisend for 7d / 30d).']);
  L([]);

  // Store Overview
  L(['STORE OVERVIEW' + ovSuffix]);
  L(['Store','Sent','Open Rate','CTR','Attributed Revenue','Total Revenue','Orders','Unsub Rate','Currency']);
  scope.forEach(sid => {{ const d = rangeData(sid); if (!d) return;
    L([sid, d.sent, pct(d.openRate), pct(d.clickRate), d.revenue, d.totalRev, d.orders, pct(d.unsubRate), d.currency]); }});
  L([]);

  // Campaign vs Automation split
  L(['CAMPAIGN vs AUTOMATION' + ovSuffix]);
  L(['Store','Campaign Sent','Campaign Open%','Campaign Revenue','Campaign Orders','Automation Sent','Automation Open%','Automation Revenue','Automation Orders','Currency']);
  scope.forEach(sid => {{ const d = rangeData(sid); if (!d) return;
    L([sid, d.campSent, pct(d.campOpen), d.campRev, d.campOrders, d.autoSent, pct(d.autoOpen), d.autoRev, d.autoOrders, d.currency]); }});
  L([]);

  // Subscriber growth
  L(['SUBSCRIBER GROWTH' + ovSuffix]);
  L(['Store','New Email Subs','Email Unsubs','Net Growth','New SMS Subs']);
  scope.forEach(sid => {{ const d = rangeData(sid); if (!d) return;
    L([sid, d.subEmail, d.unsubEmail, d.netGrowth, d.subSms]); }});
  L([]);

  // Segments
  L(['SEGMENTS']);
  L(['Store','Configured Segments']);
  document.querySelectorAll('#seg-panel .prog-row[data-store]').forEach(el => {{
    if (market !== 'all' && el.dataset.store !== market) return;
    const c = el.querySelector('.prog-count');
    L([el.dataset.store, c ? c.textContent.trim() : '']);
  }});
  L([]);

  // Campaigns (in-range + market + channel)
  L(['CAMPAIGNS (' + rangeLabel + ')']);
  L(['Store','Campaign','Channel','Send Date','Status','Sent','CTR','Open%','Opens','Clicks','Revenue','Orders','Unsub%','Currency']);
  document.querySelectorAll('#camp-tbody tr[data-store]').forEach(r => {{
    if (r.dataset.inRange === '0') return;
    if (market !== 'all' && r.dataset.store !== market) return;
    if (channel !== 'all' && !((r.dataset.channel || '').includes(channel))) return;
    const d = r.dataset;
    L([d.store, d.name, d.channel, (d.sentAt || '').slice(0, 10), d.status,
       d.sent, pct(d.ctr), pct(d.open), d.opens, d.clicks, d.rev, d.orders, pct(d.unsub), d.cur]);
  }});
  L([]);

  // Automations — flow rows + their Email/SMS message rows (market + channel)
  L(['AUTOMATIONS']);
  L(['Store','Level','Automation / Message','Channel','Status','Trigger','Sent','Open%','Click%','Placed Order%','Revenue','Orders','Spam%','Unsub%','Currency']);
  document.querySelectorAll('#auto-tbody tr.auto-flow').forEach(r => {{
    if (market !== 'all' && r.dataset.store !== market) return;
    if (channel !== 'all' && !((r.dataset.channel || '').includes(channel))) return;
    const d = r.dataset;
    L([d.store,'flow', d.name, '', d.status, d.trigger,
       d.sent, pct(d.open), pct(d.ctr), pct(d.po), d.rev, d.orders, pct(d.spam), pct(d.unsub), d.cur]);
    document.querySelectorAll('#auto-tbody tr.auto-msg').forEach(m => {{
      if (m.dataset.parent !== d.rid) return;
      const x = m.dataset;
      L([d.store,'message', x.label, x.ch, '', '',
         x.sent, pct(x.open), pct(x.ctr), pct(x.po), x.rev, x.orders, pct(x.spam), pct(x.unsub), x.cur]);
    }});
  }});
  L([]);

  // Forms (respecting current market filter)
  L(['FORMS']);
  L(['Store','Form','Type','Status','Views','Interaction%','Submit%','Signup%']);
  document.querySelectorAll('#form-tbody tr[data-store]').forEach(r => {{
    if (r.hidden) return;
    const c = r.querySelectorAll('td');
    if (c.length < 8) return;
    L([r.dataset.store, c[1].textContent.trim(), c[2].textContent.trim(), c[3].textContent.trim(),
       c[4].textContent.trim(), c[5].textContent.trim(), c[6].textContent.trim(), c[7].textContent.trim()]);
  }});

  const csv  = String.fromCharCode(0xFEFF) + lines.join('\\r\\n');
  const blob = new Blob([csv], {{ type: 'text/csv;charset=utf-8;' }});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const tag  = (market === 'all' ? 'all-markets' : market);
  const rl   = custom ? (customFrom + '_' + customTo) : (currentRange === '7' ? 'last7d' : 'last30d');
  a.href = url; a.download = 'omnisend_' + tag + '_' + rl + '.csv';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}}

// init
updateCampDateFilter();
updateCampKpis();
applyFilters();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()

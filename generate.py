#!/usr/bin/env python3
"""
Omnisend Multi-Store Dashboard Generator — V2
Filter bar: Market × Channel × Type (Overview / Campaign / Automation / Form)
Three view modes, client-side JS switching.
"""

import os
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
        {
            "alias": "by_type",
            "dateRange": {"interval": "custom", "from": date_from, "to": date_to},
            "dimensions": [{"name": "marketingActivityType"}],
            "metrics": [
                {"name": "sent"}, {"name": "attributedRevenue"},
                {"name": "attributedOrders"}, {"name": "openRate"}, {"name": "clickRate"},
            ],
        },
    ]})
    rpts = data.get("reports", [])
    totals = rpts[0].get("rows", [{}])[0] if rpts else {}
    by_type = {}
    if len(rpts) > 1:
        for row in rpts[1].get("rows", []):
            by_type[row.get("marketingActivityType", "Unknown")] = row
    return {"totals": totals, "by_type": by_type}


def fetch_subscriber_growth(key, date_from, date_to):
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


def fetch_campaigns(key, n=10):
    data = safe_get(f"{BASE}/api/campaigns", key,
                    {"status": "sent", "limit": n, "sort": "updatedAt", "direction": "desc"})
    items = []
    for c in data.get("campaigns", []):
        ch = c.get("channel", "email").lower()
        # normalise channel label
        ch_label = {"email": "EDM", "sms": "SMS", "push": "Push"}.get(ch, ch.upper())
        stats = c.get("statistics", {})
        items.append({
            "name":         c.get("content", {}).get("email", {}).get("subject") or c.get("name", "—"),
            "channel":      ch_label,
            "status":       c.get("status", "—"),
            "sent_at":      c.get("startedAt") or c.get("createdAt", ""),
            "sent":         stats.get("sent") or stats.get("messagesSent"),
            "open_rate":    stats.get("openRate"),
            "opens":        stats.get("opened") or stats.get("messagesOpened"),
            "click_rate":   stats.get("clickRate"),
            "clicks":       stats.get("clicked") or stats.get("messagesClicked"),
            "order_rate":   stats.get("ordersRate") or stats.get("placedOrderRate"),
            "orders":       stats.get("orders") or stats.get("placedOrders"),
            "revenue":      stats.get("revenue") or stats.get("attributedRevenue"),
            "fail_rate":    stats.get("failedRate") or stats.get("failedDeliveryRate"),
            "spam_rate":    stats.get("spamRate") or stats.get("markedAsSpamRate"),
            "unsub_rate":   stats.get("unsubscribeRate"),
            "unsubs":       stats.get("unsubscribed") or stats.get("messagesResultedInUnsubscribes"),
        })
    return items


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
        auto_rows.append({
            "name":     a.get("name", "—"),
            "status":   st,
            "category": cat,
            "channels": ", ".join(ch_labels) if ch_labels else "—",
            "trigger":  trigger or "—",
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
    now       = datetime.now(timezone.utc)
    date_to   = now.strftime("%Y-%m-%dT23:59:59Z")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    display_range = f"{(now - timedelta(days=30)).strftime('%b %d')} – {now.strftime('%b %d, %Y')}"
    updated_at    = now.strftime("%Y-%m-%d %H:%M UTC")

    store_data = []

    for s in STORES:
        key = os.environ.get(s["key_env"], "")
        if not key:
            print(f"⚠️  No key for {s['id']}, skipping.")
            store_data.append({**s,
                "analytics":   {"totals": {}, "by_type": {}},
                "growth":      {"subscribedEmail": 0, "unsubscribedEmail": 0, "subscribedSms": 0},
                "automations": {"total": 0, "active": 0, "by_status": {}, "by_cat": {}, "ch_msgs": {}, "rows": []},
                "segments":    {"count": 0, "plus": False},
                "campaigns":   [],
                "forms":       [],
            })
            continue

        print(f"Fetching {s['id']}…")
        store_data.append({**s,
            "analytics":   fetch_analytics(key, date_from, date_to),
            "growth":      fetch_subscriber_growth(key, date_from, date_to),
            "automations": fetch_automations(key),
            "segments":    fetch_segments(key),
            "campaigns":   fetch_campaigns(key, 10),
            "forms":       fetch_forms(key),
        })

    html = build_html(store_data, display_range, updated_at)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅  index.html generated.")


# ─── HTML builder ─────────────────────────────────────────────────────────────
def build_html(stores, display_range, updated_at):

    store_ids = [s["id"] for s in stores]

    # ── Market options for filter dropdown ──
    market_opts = '<option value="all">All Markets</option>\n'
    for s in stores:
        market_opts += f'      <option value="{s["id"]}">{s["flag"]} {s["id"]}</option>\n'

    # ────────────────────────────────────────────────────────────────────────
    # VIEW 1 — Overview: KPI cards + analytics table
    # ────────────────────────────────────────────────────────────────────────
    cards_html = ""
    for s in stores:
        a    = s["analytics"]["totals"]
        auto = s["automations"]
        seg  = s["segments"]
        seg_label = f"{seg['count']}+" if seg["plus"] else str(seg["count"])
        cards_html += f"""
        <div class="card" data-store="{s['id']}" style="border-top:3px solid {s['color']}">
          <div class="card-header">
            <span class="store-badge" style="background:{s['bg']};color:{s['color']}">{s['flag']} {s['id']}</span>
            <span class="card-currency">{s['currency']}</span>
          </div>
          <div class="card-name">{s['label']}</div>
          <div class="card-metrics">
            <div class="metric-box">
              <div class="m-label">Sent (30d)</div>
              <div class="m-value" style="color:{s['color']}">{fmt_num(a.get('sent'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">Open Rate</div>
              <div class="m-value">{fmt_pct(a.get('openRate'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">CTR</div>
              <div class="m-value">{fmt_pct(a.get('clickRate'))}</div>
            </div>
            <div class="metric-box">
              <div class="m-label">Attrib. Revenue</div>
              <div class="m-value">{fmt_rev(a.get('attributedRevenue'), s['currency'])}</div>
            </div>
          </div>
          <div class="card-footer">
            <span>📦 {fmt_num(a.get('attributedOrders'))} orders</span>
            <span>⚡ {auto['active']}/{auto['total']} flows</span>
            <span>🎯 {seg_label} segs</span>
          </div>
        </div>"""

    analytics_rows = ""
    for s in stores:
        a = s["analytics"]["totals"]
        analytics_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num">{fmt_num(a.get('sent'))}</td>
          <td><span class="heat {open_cls(a.get('openRate'))}">{fmt_pct(a.get('openRate'))}</span></td>
          <td><span class="heat {ctr_cls(a.get('clickRate'))}">{fmt_pct(a.get('clickRate'))}</span></td>
          <td class="num">{fmt_rev(a.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted">{fmt_rev(a.get('totalRevenue'), s['currency'])}</td>
          <td class="num fw6">{fmt_num(a.get('attributedOrders'))}</td>
          <td><span class="heat {unsub_cls(a.get('unsubscribeRate'))}">{fmt_pct(a.get('unsubscribeRate'))}</span></td>
        </tr>"""

    # Campaign vs Automation split (overview sub-panel)
    split_rows = ""
    for s in stores:
        bt   = s["analytics"]["by_type"]
        camp = bt.get("Campaign", {})
        auto = bt.get("Automation", {})
        split_rows += f"""
        <tr data-store="{s['id']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num">{fmt_num(camp.get('sent'))}</td>
          <td><span class="heat {open_cls(camp.get('openRate'))}">{fmt_pct(camp.get('openRate'))}</span></td>
          <td class="num">{fmt_rev(camp.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted">{fmt_num(camp.get('attributedOrders'))}</td>
          <td class="divider-col"></td>
          <td class="num">{fmt_num(auto.get('sent'))}</td>
          <td><span class="heat {open_cls(auto.get('openRate'))}">{fmt_pct(auto.get('openRate'))}</span></td>
          <td class="num">{fmt_rev(auto.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted">{fmt_num(auto.get('attributedOrders'))}</td>
        </tr>"""

    # Growth rows
    growth_rows = ""
    for s in stores:
        g   = s["growth"]
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
          <td class="num pos">{fmt_num(sub)}</td>
          <td class="num neg">−{fmt_num(uns)}</td>
          <td><span class="heat {growth_cls(net)}">{'+' if net > 0 else ''}{fmt_num(net)}</span></td>
          <td class="num muted">{fmt_num(sms) if sms else '—'}</td>
        </tr>"""

    # Segment bars
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
        for c in s["campaigns"]:
            ch = c["channel"]
            ch_cls = {"EDM": "tag-email", "SMS": "tag-sms", "Push": "tag-push"}.get(ch, "tag-email")
            st_cls = status_cls(c["status"])
            camp_rows += f"""
        <tr data-store="{s['id']}" data-channel="{ch}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span>{s['flag']} {s['id']}</span>
          </div></td>
          <td class="camp-name" title="{c['name']}">{c['name']}</td>
          <td><span class="tag {ch_cls}">{ch}</span></td>
          <td class="muted small">{fmt_date(c['sent_at'])}</td>
          <td><span class="{st_cls}">{c['status']}</span></td>
          <td class="num">{fmt_num(c['sent'])}</td>
          <td><span class="heat {open_cls(c['open_rate'])}">{fmt_pct(c['open_rate'])}</span></td>
          <td class="num muted">{fmt_num(c['opens'])}</td>
          <td><span class="heat {ctr_cls(c['click_rate'])}">{fmt_pct(c['click_rate'])}</span></td>
          <td class="num muted">{fmt_num(c['clicks'])}</td>
          <td class="num">{fmt_rev(c['revenue'], s['currency'])}</td>
          <td class="num muted">{fmt_num(c['orders'])}</td>
          <td><span class="heat {unsub_cls(c['unsub_rate'])}">{fmt_pct(c['unsub_rate'])}</span></td>
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

        for row in auto.get("rows", []):
            st_cls = status_cls(row["status"])
            auto_rows_html += f"""
        <tr data-store="{s['id']}" data-channel="{row['channels']}">
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span>{s['flag']} {s['id']}</span>
          </div></td>
          <td class="camp-name" title="{row['name']}">{row['name']}</td>
          <td><span class="tag tag-auto">{row['category']}</span></td>
          <td class="muted small">{row['channels']}</td>
          <td><span class="{st_cls}">{row['status']}</span></td>
          <td class="muted small">{row['trigger']}</td>
        </tr>"""

    if not auto_rows_html:
        auto_rows_html = '<tr class="empty-row"><td colspan="6">No automation data available</td></tr>'

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
    <label>📅 Date</label>
    <span class="filter-date-badge" id="date-badge">{display_range}</span>
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
</div>

<div class="page">

<!-- ═══════════════════════════════════════════════════════════════
     VIEW: OVERVIEW
═══════════════════════════════════════════════════════════════ -->
<div id="view-overview" class="view active">

  <div class="section-title"><span class="st-icon">🏪</span> Store Overview — Last 30 Days</div>
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
          <th>Open%</th>
          <th class="num">Opens</th>
          <th>CTR</th>
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

  <div class="section-title"><span class="st-icon">⚡</span> Automation Health</div>
  <div class="two-col">
    <div class="panel">
      <div class="panel-head">
        <span class="panel-head-title">Active Flows by Store</span>
        <span class="panel-head-sub">enabled / disabled / draft</span>
      </div>
{auto_progress}
{ch_stats_html}
    </div>
    <div class="panel">
      <div class="panel-head">
        <span class="panel-head-title" id="cat-panel-title">Flow Categories — GT-US</span>
        <span class="panel-head-sub">active / total by trigger</span>
      </div>
{cat_rows}
    </div>
  </div>

  <div class="section-title"><span class="st-icon">⚡</span> All Automations</div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Market</th>
          <th>Automation Name</th>
          <th>Category</th>
          <th>Channels</th>
          <th>Status</th>
          <th>Trigger</th>
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
const STORE_IDS = {store_ids_js};
let currentType = 'overview';

// ── View switching ────────────────────────────────────────────────────────────
function setType(t) {{
  currentType = t;
  document.querySelectorAll('.type-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.type === t));
  document.querySelectorAll('.view').forEach(v =>
    v.classList.toggle('active', v.id === 'view-' + t));
  applyFilters();
}}

// ── Main filter function ──────────────────────────────────────────────────────
function applyFilters() {{
  const market  = document.getElementById('sel-market').value;   // "all" or store id
  const channel = document.getElementById('sel-channel').value;  // "all" | "EDM" | "SMS" | "Push"

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

  // ── Overview: table rows (data-store only, no channel filter) ──
  ['analytics-tbody', 'split-tbody', 'growth-tbody'].forEach(id => {{
    const tbody = document.getElementById(id);
    if (!tbody) return;
    tbody.querySelectorAll('tr[data-store]').forEach(row => {{
      row.hidden = market !== 'all' && row.dataset.store !== market;
    }});
  }});

  // Segment bars (data-store, no channel)
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

  // ── Campaign rows (market + channel) ──
  filterDetailTable('camp-tbody',  market, channel);

  // ── Automation rows (market + channel) ──
  filterDetailTable('auto-tbody',  market, channel);

  // ── Form rows (market only, no channel) ──
  filterDetailTable('form-tbody',  market, 'all');
}}

function filterDetailTable(tbodyId, market, channel) {{
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  let anyVisible = false;
  tbody.querySelectorAll('tr[data-store]').forEach(row => {{
    const mOk = market  === 'all' || row.dataset.store   === market;
    const chOk = channel === 'all' || (row.dataset.channel && row.dataset.channel.includes(channel));
    row.hidden = !(mOk && chOk);
    if (!row.hidden) anyVisible = true;
  }});
  // empty-state row
  const empty = tbody.querySelector('tr.empty-row');
  if (empty) empty.hidden = anyVisible;
}}

// init
applyFilters();
</script>
</body>
</html>"""


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Omnisend Multi-Store Dashboard Generator — v2
Sections: Store KPIs · Email Analytics · Campaign vs Automation ·
          Recent Campaigns · Automation Health · Subscriber Growth · Segments
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

BASE = "https://api.omnisend.com"

# Automation trigger → display category
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
    "Welcome":           "👋",
    "Checkout Abandon":  "🛒",
    "Cart Abandon":      "🛒",
    "Product Abandon":   "👁",
    "Browse Abandon":    "👁",
    "Post-Purchase":     "📦",
    "Reactivation":      "🔄",
    "Anniversary":       "🎂",
    "Lifecycle":         "🎯",
    "Other":             "🔧",
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
        print(f"  GET {url} → {r.status_code}")
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
    """Overall totals + Campaign vs Automation split — 1 API call, 2 queries."""
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
    """New email/SMS subscribers + email unsubscribes via analytics/statistics."""
    # statistics API requires both dates in the same calendar year
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


def fetch_campaigns(key, n=5):
    data = safe_get(f"{BASE}/api/campaigns", key,
                    {"status": "sent", "limit": n, "sort": "updatedAt", "direction": "desc"})
    return data.get("campaigns", [])


def fetch_automations(key):
    data = safe_get(f"{BASE}/v5/automations", key)
    items = data.get("automations", [])

    by_status = {"enabled": 0, "disabled": 0, "draft": 0}
    by_cat = {}
    ch_msgs = {"email": 0, "sms": 0, "push": 0}

    for a in items:
        st = a.get("status", "draft")
        by_status[st] = by_status.get(st, 0) + 1

        trigger = a.get("trigger", "")
        cat = TRIGGER_MAP.get(trigger, "Other")

        # Refine "Lifecycle" by name keywords
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

        for msg in a.get("messages", []):
            ch = msg.get("channel", "email")
            ch_msgs[ch] = ch_msgs.get(ch, 0) + 1

    return {
        "total":      len(items),
        "active":     by_status.get("enabled", 0),
        "by_status":  by_status,
        "by_cat":     by_cat,
        "ch_msgs":    ch_msgs,
    }


def fetch_segments(key):
    data = safe_get(f"{BASE}/api/segments", key, {"limit": 100})
    segs = data.get("segments", [])
    more = data.get("paging", {}).get("hasMore", False)
    return {"count": len(segs), "plus": more}


# ─── Formatters ───────────────────────────────────────────────────────────────
def fmt_num(n):
    return f"{int(n):,}" if n is not None else "—"

def fmt_pct(n):
    return f"{n * 100:.2f}%" if n is not None else "—"

def fmt_rev(n, cur):
    if n is None:
        return "—"
    sym = {"USD": "$", "CAD": "CA$", "GBP": "£", "AUD": "A$", "EUR": "€", "JPY": "¥"}.get(cur, cur + " ")
    return f"{sym}{int(n):,}" if cur == "JPY" else f"{sym}{n:,.0f}"

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


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    now       = datetime.now(timezone.utc)
    date_to   = now.strftime("%Y-%m-%dT23:59:59Z")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    display_range = f"{(now - timedelta(days=30)).strftime('%b %d')} – {now.strftime('%b %d, %Y')}"
    updated_at    = now.strftime("%Y-%m-%d %H:%M UTC")

    store_data    = []
    all_campaigns = []

    for s in STORES:
        key = os.environ.get(s["key_env"], "")
        if not key:
            print(f"⚠️  No key for {s['id']}, skipping.")
            store_data.append({**s,
                "analytics":   {"totals": {}, "by_type": {}},
                "growth":      {"subscribedEmail": 0, "unsubscribedEmail": 0, "subscribedSms": 0},
                "automations": {"total": 0, "active": 0, "by_status": {}, "by_cat": {}, "ch_msgs": {}},
                "segments":    {"count": 0, "plus": False},
                "campaigns":   [],
            })
            continue

        print(f"Fetching {s['id']}…")
        analytics   = fetch_analytics(key, date_from, date_to)
        growth      = fetch_subscriber_growth(key, date_from, date_to)
        automations = fetch_automations(key)
        segments    = fetch_segments(key)
        campaigns   = fetch_campaigns(key, 3)

        store_data.append({**s,
            "analytics":   analytics,
            "growth":      growth,
            "automations": automations,
            "segments":    segments,
            "campaigns":   campaigns,
        })
        for c in campaigns:
            c["_store_id"]    = s["id"]
            c["_store_color"] = s["color"]
            c["_store_flag"]  = s["flag"]
            all_campaigns.append(c)

    all_campaigns.sort(key=lambda c: c.get("startedAt") or c.get("createdAt", ""), reverse=True)

    html = build_html(store_data, all_campaigns[:15], display_range, updated_at)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅  index.html generated.")


# ─── HTML builder ─────────────────────────────────────────────────────────────
def build_html(stores, campaigns, display_range, updated_at):

    # ── 1. Store KPI cards ──
    cards_html = ""
    for s in stores:
        a    = s["analytics"]["totals"]
        auto = s["automations"]
        seg  = s["segments"]
        seg_label = f"{seg['count']}+" if seg["plus"] else str(seg["count"])
        cards_html += f"""
        <div class="card" style="border-top:3px solid {s['color']}">
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

    # ── 2. Analytics table rows ──
    table_rows = ""
    for s in stores:
        a = s["analytics"]["totals"]
        table_rows += f"""
        <tr>
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

    # ── 3. Campaign vs Automation split ──
    split_rows = ""
    for s in stores:
        bt   = s["analytics"]["by_type"]
        camp = bt.get("Campaign", {})
        auto = bt.get("Automation", {})
        split_rows += f"""
        <tr>
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

    # ── 4. Recent campaigns table ──
    camp_rows = ""
    for c in campaigns:
        subj    = c.get("content", {}).get("email", {}).get("subject") or c.get("name", "—")
        channel = c.get("channel", "email").upper()
        ch_cls  = "tag-email" if channel == "EMAIL" else ("tag-sms" if channel == "SMS" else "tag-push")
        date_raw = c.get("startedAt") or c.get("createdAt", "")
        try:
            dt       = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d, %Y")
        except Exception:
            date_str = date_raw[:10]
        camp_rows += f"""
        <tr>
          <td><div class="store-cell">
            <span class="dot" style="background:{c['_store_color']}"></span>
            <span>{c['_store_flag']} {c['_store_id']}</span>
          </div></td>
          <td class="camp-name">{subj}</td>
          <td><span class="tag {ch_cls}">{channel}</span></td>
          <td class="muted">{date_str}</td>
          <td><span class="status-sent">✓ Sent</span></td>
        </tr>"""

    # ── 5. Automations — progress bars ──
    auto_progress = ""
    for s in stores:
        auto  = s["automations"]
        total = max(auto["total"], 1)
        pct   = round(auto["active"] / total * 100)
        bs    = auto.get("by_status", {})
        auto_progress += f"""
        <div class="prog-row">
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

    # ── 5b. Automations — category breakdown (GT-US only, richest data) ──
    cat_rows = ""
    gt_us = next((s for s in stores if s["id"] == "GT-US"), None)
    if gt_us:
        for cat, counts in sorted(gt_us["automations"].get("by_cat", {}).items(),
                                  key=lambda x: -x[1]["total"]):
            icon    = CAT_ICONS.get(cat, "🔧")
            enabled = counts["enabled"]
            total_c = counts["total"]
            pct_c   = round(enabled / max(total_c, 1) * 100)
            cat_rows += f"""
            <div class="cat-row">
              <div class="cat-label">{icon} {cat}</div>
              <div class="prog-track" style="flex:1;margin:0 10px">
                <div class="prog-fill" style="width:{pct_c}%;background:#2563eb"></div>
              </div>
              <div class="cat-count">{enabled}/{total_c} active</div>
            </div>"""

    # ── 6. Subscriber growth ──
    growth_rows = ""
    for s in stores:
        g   = s["growth"]
        sub = g.get("subscribedEmail", 0) or 0
        uns = g.get("unsubscribedEmail", 0) or 0
        sms = g.get("subscribedSms", 0) or 0
        net = sub - uns
        growth_rows += f"""
        <tr>
          <td><div class="store-cell">
            <span class="dot" style="background:{s['color']}"></span>
            <span class="fw6">{s['flag']} {s['id']}</span>
          </div></td>
          <td class="num pos">{fmt_num(sub)}</td>
          <td class="num neg">−{fmt_num(uns)}</td>
          <td><span class="heat {growth_cls(net)}">{'+' if net > 0 else ''}{fmt_num(net)}</span></td>
          <td class="num muted">{fmt_num(sms) if sms else '—'}</td>
        </tr>"""

    # ── 7. Segments ──
    max_seg  = max((s["segments"]["count"] for s in stores), default=1)
    seg_rows = ""
    for s in stores:
        seg   = s["segments"]
        label = f"{seg['count']}+" if seg["plus"] else str(seg["count"])
        width = round(seg["count"] / max(max_seg, 1) * 100)
        seg_rows += f"""
        <div class="prog-row">
          <div class="prog-label" style="color:{s['color']}">{s['id']}</div>
          <div class="prog-track">
            <div class="prog-fill" style="width:{max(width,4)}%;background:{s['color']};opacity:.75"></div>
          </div>
          <div class="prog-count">{label}</div>
        </div>"""

    # ── channel breakdown for automations footer ──
    total_ch = {}
    for s in stores:
        for ch, cnt in s["automations"].get("ch_msgs", {}).items():
            total_ch[ch] = total_ch.get(ch, 0) + cnt

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
    background: #f0f2f5;
    color: #1e293b;
    font-size: 14px;
    line-height: 1.5;
  }}

  /* ── Top bar ── */
  .topbar {{
    background: #fff;
    border-bottom: 1px solid #e2e8f0;
    padding: 0 28px;
    height: 56px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
  }}
  .topbar-left {{ display: flex; align-items: center; gap: 14px; }}
  .topbar-logo {{ font-size: 16px; font-weight: 700; color: #0f172a; letter-spacing: -.3px; }}
  .topbar-logo span {{ color: #2563eb; }}
  .topbar-range {{
    font-size: 11px; color: #64748b; background: #f1f5f9;
    padding: 3px 10px; border-radius: 20px; border: 1px solid #e2e8f0;
  }}
  .topbar-nav {{ display: flex; gap: 2px; }}
  .topbar-nav a {{
    font-size: 12px; font-weight: 500; color: #64748b;
    padding: 5px 10px; border-radius: 6px; text-decoration: none;
    transition: background .1s, color .1s;
  }}
  .topbar-nav a:hover {{ background: #f1f5f9; color: #0f172a; }}
  .topbar-right {{ display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8; }}
  .live-dot {{
    width: 6px; height: 6px; background: #22c55e; border-radius: 50%;
    display: inline-block; animation: blink 2s infinite;
  }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}

  /* ── Layout ── */
  .page {{ max-width: 1440px; margin: 0 auto; padding: 24px 20px 60px; }}

  /* ── Section label ── */
  .section-title {{
    font-size: 11px; font-weight: 700; letter-spacing: 1px;
    text-transform: uppercase; color: #94a3b8;
    margin: 32px 0 14px;
    display: flex; align-items: center; gap: 10px;
  }}
  .section-title .st-icon {{ font-size: 14px; }}
  .section-title::after {{
    content: ''; flex: 1; height: 1px; background: #e2e8f0;
  }}

  /* ── Cards grid ── */
  .cards-grid {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 12px;
    margin-bottom: 8px;
  }}
  @media (max-width: 1280px) {{ .cards-grid {{ grid-template-columns: repeat(4,1fr); }} }}
  @media (max-width: 700px)  {{ .cards-grid {{ grid-template-columns: repeat(2,1fr); }} }}

  .card {{
    background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 16px 14px 12px;
    transition: box-shadow .15s, transform .15s;
  }}
  .card:hover {{ box-shadow: 0 4px 16px rgba(0,0,0,.07); transform: translateY(-1px); }}
  .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
  .store-badge {{ font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 20px; }}
  .card-currency {{ font-size: 11px; color: #94a3b8; font-weight: 500; }}
  .card-name {{ font-size: 11px; color: #64748b; margin-bottom: 12px; font-weight: 500; }}
  .card-metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }}
  .m-label {{ font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 1px; }}
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
    padding: 14px 18px 12px;
    border-bottom: 1px solid #f1f5f9;
    display: flex; align-items: baseline; gap: 8px;
  }}
  .panel-head-title {{ font-size: 13px; font-weight: 700; color: #0f172a; }}
  .panel-head-sub {{ font-size: 11px; color: #94a3b8; }}

  /* ── Tables ── */
  .table-wrap {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; margin-bottom: 14px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #f8fafc; text-align: left;
    padding: 9px 14px; font-size: 11px; font-weight: 700;
    color: #64748b; text-transform: uppercase; letter-spacing: .6px;
    border-bottom: 1px solid #e2e8f0; white-space: nowrap;
  }}
  thead th.num {{ text-align: right; }}
  tbody td {{ padding: 11px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #fafbfc; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #94a3b8; }}
  .fw6 {{ font-weight: 600; }}
  .pos {{ color: #16a34a; font-weight: 600; }}
  .neg {{ color: #dc2626; font-weight: 500; }}

  /* ── Divider column in split table ── */
  .divider-col {{ width: 1px; background: #e2e8f0; padding: 0; }}
  thead th.divider-col {{ background: #e2e8f0; }}

  /* ── Store cell ── */
  .store-cell {{ display: flex; align-items: center; gap: 8px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}

  /* ── Heatmap badges ── */
  .heat {{
    display: inline-block; padding: 2px 8px; border-radius: 5px;
    font-size: 12px; font-weight: 600;
  }}
  .h-green  {{ background: #dcfce7; color: #15803d; }}
  .h-yellow {{ background: #fef9c3; color: #a16207; }}
  .h-red    {{ background: #fee2e2; color: #b91c1c; }}
  .h-gray   {{ background: #f1f5f9; color: #64748b; }}

  /* ── Two-col layout ── */
  .two-col {{
    display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;
  }}
  @media (max-width: 860px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  /* ── Progress rows ── */
  .prog-row {{
    display: flex; align-items: center; gap: 10px;
    padding: 9px 18px; border-bottom: 1px solid #f8fafc;
  }}
  .prog-row:last-child {{ border-bottom: none; }}
  .prog-label {{ width: 86px; flex-shrink: 0; font-size: 12px; font-weight: 700; }}
  .prog-track {{ flex: 1; height: 7px; background: #f1f5f9; border-radius: 4px; overflow: hidden; }}
  .prog-fill {{ height: 100%; border-radius: 4px; }}
  .prog-count {{ width: 40px; text-align: right; font-size: 12px; color: #64748b; flex-shrink: 0; font-weight: 500; }}
  .prog-meta {{ display: flex; align-items: center; gap: 5px; flex-shrink: 0; }}

  /* ── Category rows (automation) ── */
  .cat-row {{
    display: flex; align-items: center; gap: 8px;
    padding: 8px 18px; border-bottom: 1px solid #f8fafc;
  }}
  .cat-row:last-child {{ border-bottom: none; }}
  .cat-label {{ width: 160px; flex-shrink: 0; font-size: 12px; color: #374151; font-weight: 500; }}
  .cat-count {{ width: 90px; text-align: right; font-size: 11px; color: #64748b; flex-shrink: 0; }}

  /* ── Pills ── */
  .pill {{
    font-size: 10px; font-weight: 600; padding: 1px 6px;
    border-radius: 10px; flex-shrink: 0;
  }}
  .pill-green {{ background: #dcfce7; color: #16a34a; }}
  .pill-gray  {{ background: #f1f5f9; color: #64748b; }}
  .pill-dim   {{ background: #fef9c3; color: #92400e; }}

  /* ── Tags ── */
  .tag {{ display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; }}
  .tag-email {{ background: #dbeafe; color: #1d4ed8; }}
  .tag-sms   {{ background: #dcfce7; color: #15803d; }}
  .tag-push  {{ background: #ede9fe; color: #7c3aed; }}

  /* ── Campaign name ── */
  .camp-name {{ font-weight: 500; max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}

  /* ── Status ── */
  .status-sent {{ font-size: 12px; color: #16a34a; font-weight: 600; }}

  /* ── Channel mini badges ── */
  .ch-stat {{ display: flex; gap: 12px; padding: 10px 18px; border-top: 1px solid #f1f5f9; }}
  .ch-item {{ display: flex; align-items: center; gap: 5px; font-size: 11px; color: #64748b; }}
  .ch-dot {{ width: 8px; height: 8px; border-radius: 50%; }}

  /* ── Footer ── */
  .footer {{
    margin-top: 48px; padding: 18px 0 0; border-top: 1px solid #e2e8f0;
    display: flex; justify-content: space-between; font-size: 11px; color: #94a3b8;
  }}

  /* ── Legend ── */
  .legend {{
    display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px;
    font-size: 11px; color: #64748b;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}

  /* ── Section anchor scroll offset ── */
  .anchor {{ scroll-margin-top: 68px; }}
</style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">Omnisend <span>Dashboard</span></div>
    <div class="topbar-range">📅 {display_range}</div>
  </div>
  <nav class="topbar-nav">
    <a href="#analytics">📊 Analytics</a>
    <a href="#campaigns">📧 Campaigns</a>
    <a href="#automations">⚡ Automations</a>
    <a href="#growth">🌱 Growth</a>
    <a href="#segments">🎯 Segments</a>
  </nav>
  <div class="topbar-right">
    <span class="live-dot"></span>
    Updated weekly &nbsp;·&nbsp; {updated_at}
  </div>
</div>

<div class="page">

  <!-- STORE CARDS -->
  <div class="section-title"><span class="st-icon">🏪</span> Store Overview — Last 30 Days</div>
  <div class="cards-grid">
{cards_html}
  </div>

  <!-- ANALYTICS TABLE -->
  <div class="section-title anchor" id="analytics"><span class="st-icon">📊</span> Email Performance Analytics</div>
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
      <tbody>{table_rows}</tbody>
    </table>
  </div>

  <!-- CAMPAIGN vs AUTOMATION SPLIT -->
  <div class="section-title anchor" id="campaigns"><span class="st-icon">📧</span> Campaigns</div>

  <div class="panel">
    <div class="panel-head">
      <span class="panel-head-title">Campaign vs Automation Performance</span>
      <span class="panel-head-sub">Last 30 days — attributed revenue by source type</span>
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
          <th class="num">Sent</th>
          <th>Open%</th>
          <th class="num">Revenue</th>
          <th class="num">Orders</th>
          <th class="divider-col" style="display:none"></th>
          <th class="num">Sent</th>
          <th>Open%</th>
          <th class="num">Revenue</th>
          <th class="num">Orders</th>
        </tr>
      </thead>
      <tbody>{split_rows}</tbody>
    </table>
  </div>

  <!-- RECENT CAMPAIGNS -->
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Store</th>
          <th>Campaign / Subject</th>
          <th>Channel</th>
          <th>Sent Date</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>{camp_rows}</tbody>
    </table>
  </div>

  <!-- AUTOMATIONS -->
  <div class="section-title anchor" id="automations"><span class="st-icon">⚡</span> Automation Health</div>
  <div class="two-col">

    <!-- Active / Total per store -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-head-title">Active Flows by Store</span>
        <span class="panel-head-sub">enabled / disabled / draft</span>
      </div>
{auto_progress}
      <div class="ch-stat">
        <div class="ch-item"><span class="ch-dot" style="background:#1d4ed8"></span>Email messages: {fmt_num(total_ch.get('email'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#16a34a"></span>SMS messages: {fmt_num(total_ch.get('sms'))}</div>
        <div class="ch-item"><span class="ch-dot" style="background:#7c3aed"></span>Push messages: {fmt_num(total_ch.get('push'))}</div>
      </div>
    </div>

    <!-- Category breakdown (GT-US) -->
    <div class="panel">
      <div class="panel-head">
        <span class="panel-head-title">Flow Categories — GT-US</span>
        <span class="panel-head-sub">active / total by trigger type</span>
      </div>
{cat_rows}
    </div>

  </div>

  <!-- SUBSCRIBER GROWTH -->
  <div class="section-title anchor" id="growth"><span class="st-icon">🌱</span> Subscriber Growth <span style="font-size:11px;font-weight:400;color:#94a3b8;text-transform:none;letter-spacing:0">— via forms &amp; signup sources, last 30 days</span></div>
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
      <tbody>{growth_rows}</tbody>
    </table>
  </div>

  <!-- SEGMENTS -->
  <div class="section-title anchor" id="segments"><span class="st-icon">🎯</span> Segment Coverage</div>
  <div class="panel">
    <div class="panel-head">
      <span class="panel-head-title">Configured Segments per Store</span>
      <span class="panel-head-sub">lifecycle · behavioral · membership · product interest</span>
    </div>
{seg_rows}
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <div>Omnisend Multi-Store · 7 brands · Giraffe Tools &amp; Gitryin US</div>
    <div>Auto-refreshes every Monday 08:00 UTC · {updated_at}</div>
  </div>

</div>
</body>
</html>"""


if __name__ == "__main__":
    main()

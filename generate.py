#!/usr/bin/env python3
"""
Omnisend Multi-Store Dashboard Generator
Fetches live data from 7 stores via Omnisend REST API and generates index.html
Runs weekly via GitHub Actions.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone

# ─── Store config ─────────────────────────────────────────────────────────────
STORES = [
    {"id": "GT-US",      "flag": "🇺🇸", "label": "Giraffe Tools US", "currency": "USD", "color": "#2563eb", "bg": "#eff6ff", "key_env": "API_KEY_GT_US"},
    {"id": "GT-CA",      "flag": "🇨🇦", "label": "Giraffe Tools CA", "currency": "CAD", "color": "#dc2626", "bg": "#fef2f2", "key_env": "API_KEY_GT_CA"},
    {"id": "GT-UK",      "flag": "🇬🇧", "label": "Giraffe Tools UK", "currency": "GBP", "color": "#7c3aed", "bg": "#f5f3ff", "key_env": "API_KEY_GT_UK"},
    {"id": "GT-AU",      "flag": "🇦🇺", "label": "Giraffe Tools AU", "currency": "AUD", "color": "#ea580c", "bg": "#fff7ed", "key_env": "API_KEY_GT_AU"},
    {"id": "GT-DE",      "flag": "🇩🇪", "label": "Giraffe Tools DE", "currency": "EUR", "color": "#ca8a04", "bg": "#fefce8", "key_env": "API_KEY_GT_DE"},
    {"id": "GT-JP",      "flag": "🇯🇵", "label": "Giraffe Tools JP", "currency": "JPY", "color": "#db2777", "bg": "#fdf2f8", "key_env": "API_KEY_GT_JP"},
    {"id": "Gitryin-US", "flag": "⚡",  "label": "Gitryin US",       "currency": "USD", "color": "#0891b2", "bg": "#ecfeff", "key_env": "API_KEY_GITRYIN_US"},
]

BASE = "https://api.omnisend.com"


# ─── API helpers ──────────────────────────────────────────────────────────────
def headers(key):
    return {"X-API-KEY": key, "Content-Type": "application/json"}


def safe_get(url, key, params=None):
    try:
        r = requests.get(url, headers=headers(key), params=params, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"  GET {url} → {e}")
    return {}


def safe_post(url, key, payload):
    try:
        r = requests.post(url, headers=headers(key), json=payload, timeout=20)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  POST {url} → {r.status_code}: {r.text[:200]}")
    except Exception as e:
        print(f"  POST {url} → {e}")
    return {}


# ─── Data fetchers ────────────────────────────────────────────────────────────
def fetch_analytics(key, date_from, date_to):
    data = safe_post(f"{BASE}/v3/analytics/reports", key, {"queries": [{"alias": "p",
        "dateRange": {"interval": "custom", "from": date_from, "to": date_to},
        "metrics": [
            {"name": "sent"}, {"name": "openRate"}, {"name": "clickRate"},
            {"name": "attributedRevenue"}, {"name": "unsubscribeRate"},
            {"name": "totalRevenue"}, {"name": "attributedOrders"},
        ]}]})
    rows = data.get("reports", [{}])[0].get("rows", [])
    return rows[0] if rows else {}


def fetch_campaigns(key, n=5):
    data = safe_get(f"{BASE}/v3/campaigns", key,
                    {"status": "sent", "limit": n, "sort": "createdAt", "direction": "desc"})
    return data.get("campaigns", [])


def fetch_automations(key):
    data = safe_get(f"{BASE}/v5/automations", key)
    items = data.get("automations", [])
    active = sum(1 for a in items if a.get("status") == "enabled")
    return {"total": len(items), "active": active, "items": items}


def fetch_segments(key):
    data = safe_get(f"{BASE}/v3/segments", key, {"limit": 50})
    segs = data.get("segments", [])
    more = data.get("paging", {}).get("hasMore", False)
    return {"count": len(segs), "plus": more}


# ─── Formatters ───────────────────────────────────────────────────────────────
def fmt_num(n):
    return f"{int(n):,}" if n is not None else "—"


def fmt_pct(n):
    return f"{n*100:.2f}%" if n is not None else "—"


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


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    date_to   = now.strftime("%Y-%m-%dT23:59:59Z")
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")
    display_range = f"{(now - timedelta(days=30)).strftime('%b %d')} – {now.strftime('%b %d, %Y')}"
    updated_at = now.strftime("%Y-%m-%d %H:%M UTC")

    store_data = []
    all_campaigns = []

    for s in STORES:
        key = os.environ.get(s["key_env"], "")
        if not key:
            print(f"⚠️  No API key for {s['id']}, skipping.")
            store_data.append({**s, "analytics": {}, "automations": {"total": 0, "active": 0}, "segments": {"count": 0, "plus": False}, "campaigns": []})
            continue

        print(f"Fetching {s['id']}…")
        analytics    = fetch_analytics(key, date_from, date_to)
        automations  = fetch_automations(key)
        segments     = fetch_segments(key)
        campaigns    = fetch_campaigns(key, 3)

        store_data.append({**s, "analytics": analytics, "automations": automations, "segments": segments, "campaigns": campaigns})
        for c in campaigns:
            c["_store_id"]    = s["id"]
            c["_store_color"] = s["color"]
            c["_store_flag"]  = s["flag"]
            all_campaigns.append(c)

    # Sort campaigns by startedAt desc
    all_campaigns.sort(key=lambda c: c.get("startedAt", ""), reverse=True)
    top_campaigns = all_campaigns[:12]

    html = build_html(store_data, top_campaigns, display_range, updated_at)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅  index.html generated.")


# ─── HTML builder ─────────────────────────────────────────────────────────────
def build_html(stores, campaigns, display_range, updated_at):

    # ── Summary cards ──
    cards_html = ""
    for s in stores:
        a = s["analytics"]
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
            <span>🎯 {seg_label} segments</span>
          </div>
        </div>"""

    # ── Analytics table rows ──
    table_rows = ""
    for s in stores:
        a = s["analytics"]
        table_rows += f"""
        <tr>
          <td>
            <div class="store-cell">
              <span class="dot" style="background:{s['color']}"></span>
              <span class="store-name-cell">{s['flag']} {s['id']}</span>
            </div>
          </td>
          <td class="num">{fmt_num(a.get('sent'))}</td>
          <td><span class="heat {open_cls(a.get('openRate'))}">{fmt_pct(a.get('openRate'))}</span></td>
          <td><span class="heat {ctr_cls(a.get('clickRate'))}">{fmt_pct(a.get('clickRate'))}</span></td>
          <td class="num">{fmt_rev(a.get('attributedRevenue'), s['currency'])}</td>
          <td class="num muted">{fmt_rev(a.get('totalRevenue'), s['currency'])}</td>
          <td class="num"><strong>{fmt_num(a.get('attributedOrders'))}</strong></td>
          <td><span class="heat {unsub_cls(a.get('unsubscribeRate'))}">{fmt_pct(a.get('unsubscribeRate'))}</span></td>
        </tr>"""

    # ── Automation progress bars ──
    auto_rows = ""
    for s in stores:
        auto = s["automations"]
        total = max(auto["total"], 1)
        pct   = round(auto["active"] / total * 100)
        auto_rows += f"""
        <div class="prog-row">
          <div class="prog-label" style="color:{s['color']}">{s['id']}</div>
          <div class="prog-track">
            <div class="prog-fill" style="width:{pct}%;background:{s['color']}"></div>
          </div>
          <div class="prog-count">{auto['active']} / {auto['total']}</div>
        </div>"""

    # ── Segment bars ──
    # max count for scaling
    max_seg = max((s["segments"]["count"] for s in stores), default=1)
    seg_rows = ""
    for s in stores:
        seg = s["segments"]
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

    # ── Campaign rows ──
    camp_rows = ""
    for c in campaigns:
        cname   = c.get("content", {}).get("email", {}).get("subject") or c.get("name", "—")
        channel = c.get("channel", "email").upper()
        ch_cls  = "tag-email" if channel == "EMAIL" else "tag-sms"
        date_raw = c.get("startedAt") or c.get("createdAt", "")
        try:
            dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
            date_str = dt.strftime("%b %d, %Y")
        except Exception:
            date_str = date_raw[:10]
        camp_rows += f"""
        <tr>
          <td>
            <div class="store-cell">
              <span class="dot" style="background:{c['_store_color']}"></span>
              <span>{c['_store_flag']} {c['_store_id']}</span>
            </div>
          </td>
          <td class="camp-name">{cname}</td>
          <td><span class="tag {ch_cls}">{channel}</span></td>
          <td class="muted">{date_str}</td>
          <td><span class="status-sent">✓ Sent</span></td>
        </tr>"""

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
    background: #f8fafc;
    color: #1e293b;
    font-size: 14px;
    line-height: 1.5;
  }}

  /* ── Top bar ── */
  .topbar {{
    background: #fff;
    border-bottom: 1px solid #e2e8f0;
    padding: 0 32px;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .topbar-left {{
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .topbar-logo {{
    font-size: 17px;
    font-weight: 700;
    color: #0f172a;
    letter-spacing: -.3px;
  }}
  .topbar-logo span {{ color: #2563eb; }}
  .topbar-range {{
    font-size: 12px;
    color: #64748b;
    background: #f1f5f9;
    padding: 4px 10px;
    border-radius: 20px;
    border: 1px solid #e2e8f0;
  }}
  .topbar-right {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: #94a3b8;
  }}
  .live-dot {{
    width: 7px; height: 7px;
    background: #22c55e;
    border-radius: 50%;
    display: inline-block;
    animation: blink 2s infinite;
  }}
  @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:.3}} }}

  /* ── Layout ── */
  .page {{ max-width: 1400px; margin: 0 auto; padding: 28px 24px 60px; }}

  /* ── Section label ── */
  .section-title {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: #e2e8f0;
  }}

  /* ── Cards grid ── */
  .cards-grid {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 14px;
    margin-bottom: 36px;
  }}
  @media (max-width: 1200px) {{ .cards-grid {{ grid-template-columns: repeat(4,1fr); }} }}
  @media (max-width: 700px)  {{ .cards-grid {{ grid-template-columns: repeat(2,1fr); }} }}

  .card {{
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 18px 16px 14px;
    transition: box-shadow .15s, transform .15s;
  }}
  .card:hover {{ box-shadow: 0 4px 20px rgba(0,0,0,.08); transform: translateY(-2px); }}
  .card-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }}
  .store-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 20px;
  }}
  .card-currency {{
    font-size: 11px;
    color: #94a3b8;
    font-weight: 500;
  }}
  .card-name {{
    font-size: 12px;
    color: #64748b;
    margin-bottom: 14px;
    font-weight: 500;
  }}
  .card-metrics {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 14px;
  }}
  .metric-box {{ }}
  .m-label {{
    font-size: 10px;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: .6px;
    margin-bottom: 2px;
  }}
  .m-value {{
    font-size: 16px;
    font-weight: 700;
    color: #0f172a;
    line-height: 1.2;
  }}
  .card-footer {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    border-top: 1px solid #f1f5f9;
    padding-top: 10px;
  }}
  .card-footer span {{
    font-size: 11px;
    color: #64748b;
    background: #f8fafc;
    padding: 2px 7px;
    border-radius: 5px;
    border: 1px solid #e2e8f0;
  }}

  /* ── Tables ── */
  .table-wrap {{
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 28px;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #f8fafc;
    text-align: left;
    padding: 10px 14px;
    font-size: 11px;
    font-weight: 700;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: .7px;
    border-bottom: 1px solid #e2e8f0;
    white-space: nowrap;
  }}
  tbody td {{
    padding: 12px 14px;
    border-bottom: 1px solid #f1f5f9;
    vertical-align: middle;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #f8fafc; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .muted {{ color: #94a3b8; }}

  /* ── Store cell ── */
  .store-cell {{ display: flex; align-items: center; gap: 8px; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
  .store-name-cell {{ font-weight: 600; }}

  /* ── Heatmap ── */
  .heat {{
    display: inline-block;
    padding: 3px 8px;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 600;
  }}
  .h-green  {{ background: #dcfce7; color: #15803d; }}
  .h-yellow {{ background: #fef9c3; color: #a16207; }}
  .h-red    {{ background: #fee2e2; color: #b91c1c; }}
  .h-gray   {{ background: #f1f5f9; color: #94a3b8; }}

  /* ── Two-col layout ── */
  .two-col {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
    margin-bottom: 28px;
  }}
  @media (max-width: 800px) {{ .two-col {{ grid-template-columns: 1fr; }} }}

  .panel {{
    background: #fff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px 24px;
  }}
  .panel-title {{
    font-size: 13px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 18px;
    padding-bottom: 12px;
    border-bottom: 1px solid #f1f5f9;
    display: flex;
    align-items: center;
    gap: 8px;
  }}

  /* ── Progress rows ── */
  .prog-row {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 13px;
  }}
  .prog-row:last-child {{ margin-bottom: 0; }}
  .prog-label {{
    width: 80px;
    flex-shrink: 0;
    font-size: 12px;
    font-weight: 700;
  }}
  .prog-track {{
    flex: 1;
    height: 8px;
    background: #f1f5f9;
    border-radius: 4px;
    overflow: hidden;
  }}
  .prog-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width .5s ease;
  }}
  .prog-count {{
    width: 52px;
    text-align: right;
    font-size: 12px;
    color: #64748b;
    flex-shrink: 0;
    font-weight: 500;
  }}

  /* ── Campaign name ── */
  .camp-name {{
    font-weight: 500;
    max-width: 320px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}

  /* ── Tags ── */
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 5px;
    font-size: 11px;
    font-weight: 600;
  }}
  .tag-email {{ background: #dbeafe; color: #1d4ed8; }}
  .tag-sms   {{ background: #dcfce7; color: #15803d; }}
  .status-sent {{ font-size: 12px; color: #16a34a; font-weight: 600; }}

  /* ── Footer ── */
  .footer {{
    margin-top: 40px;
    padding: 20px 0 0;
    border-top: 1px solid #e2e8f0;
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: #94a3b8;
  }}

  /* ── Legend ── */
  .legend {{
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 10px;
    font-size: 11px;
    color: #64748b;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 5px; }}
</style>
</head>
<body>

<!-- TOP BAR -->
<div class="topbar">
  <div class="topbar-left">
    <div class="topbar-logo">Omnisend <span>Dashboard</span></div>
    <div class="topbar-range">📅 {display_range}</div>
  </div>
  <div class="topbar-right">
    <span class="live-dot"></span>
    Auto-updated weekly &nbsp;·&nbsp; Last update: {updated_at}
  </div>
</div>

<div class="page">

  <!-- STORE CARDS -->
  <div class="section-title">Store Overview — Last 30 Days</div>
  <div class="cards-grid">
{cards_html}
  </div>

  <!-- ANALYTICS TABLE -->
  <div class="section-title">Performance Analytics</div>
  <div class="legend">
    <div class="legend-item"><span class="heat h-green">●</span> Open ≥45% / CTR ≥2.5% / Unsub ≤0.4%</div>
    <div class="legend-item"><span class="heat h-yellow">●</span> Moderate</div>
    <div class="legend-item"><span class="heat h-red">●</span> Needs attention</div>
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
          <th class="num">Total Revenue</th>
          <th class="num">Orders</th>
          <th>Unsub Rate</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
  </div>

  <!-- AUTOMATION + SEGMENTS -->
  <div class="section-title">Automation &amp; Segment Health</div>
  <div class="two-col">
    <div class="panel">
      <div class="panel-title">⚡ Automation Health <span style="font-size:11px;font-weight:400;color:#94a3b8">Active / Total flows</span></div>
{auto_rows}
    </div>
    <div class="panel">
      <div class="panel-title">🎯 Segment Coverage <span style="font-size:11px;font-weight:400;color:#94a3b8">Configured segments count</span></div>
{seg_rows}
    </div>
  </div>

  <!-- RECENT CAMPAIGNS -->
  <div class="section-title">Recent Campaigns</div>
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
      <tbody>
{camp_rows}
      </tbody>
    </table>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <div>Omnisend MCP · 7 stores · Giraffe Tools &amp; Gitryin US</div>
    <div>Auto-refreshes every Monday · {updated_at}</div>
  </div>

</div>
</body>
</html>"""


if __name__ == "__main__":
    main()

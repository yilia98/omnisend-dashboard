#!/usr/bin/env python3
"""TEMP probe — discover Omnisend automation (workflow) analytics shape.
Replaces generate.py for ONE run on a throwaway branch. Does not write index.html."""
import os, re, json
import requests
from datetime import datetime, timedelta, timezone

BASE = "https://api.omnisend.com"
STORES = [("GT-US","API_KEY_GT_US"),("GT-CA","API_KEY_GT_CA"),("GT-UK","API_KEY_GT_UK"),
          ("GT-AU","API_KEY_GT_AU"),("GT-DE","API_KEY_GT_DE"),("GT-JP","API_KEY_GT_JP"),
          ("Gitryin-US","API_KEY_GITRYIN_US")]

def hdrs(key):
    return {"X-API-KEY": key, "Content-Type": "application/json",
            "Omnisend-Version": datetime.now(timezone.utc).strftime("%Y-%m-01")}

def post(url, key, payload):
    try:
        r = requests.post(url, headers=hdrs(key), json=payload, timeout=30)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    except Exception as e:
        return -1, str(e)

def get(url, key, params=None):
    try:
        r = requests.get(url, headers=hdrs(key), params=params, timeout=30)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    except Exception as e:
        return -1, str(e)

def reports(key, dfrom, dto, dims, metrics):
    return post(f"{BASE}/api/analytics/reports", key, {"queries":[{
        "alias":"q","dateRange":{"interval":"custom","from":dfrom,"to":dto},
        "dimensions":[{"name":d} for d in dims],
        "metrics":[{"name":m} for m in metrics]}]})

def discover_metrics(key, dfrom, dto, dims, cand):
    metrics = list(cand)
    for _ in range(len(cand)+1):
        sc, r = reports(key, dfrom, dto, dims, metrics)
        if sc == 200:
            reps = r.get("reports",[]) if isinstance(r,dict) else []
            rows = reps[0].get("rows",[]) if reps else []
            return metrics, rows
        bad = set()
        if isinstance(r, dict):
            for e in r.get("errors",[]):
                m = re.search(r"metrics\[(\d+)\]", e.get("field",""))
                if m: bad.add(int(m.group(1)))
        if not bad:
            print(f"    non-metric error for dims={dims}: {json.dumps(r)[:300] if isinstance(r,dict) else str(r)[:300]}")
            return None, []
        metrics = [m for i,m in enumerate(metrics) if i not in bad]
        if not metrics: return [], []
    return metrics, []

def main():
    now = datetime.now(timezone.utc)
    d_to = now.strftime("%Y-%m-%dT23:59:59Z")
    d_from = (now - timedelta(days=120)).strftime("%Y-%m-%dT00:00:00Z")
    key=sid=""
    for name,env in STORES:
        k=os.environ.get(env,"")
        if k: key,sid=k,name; break
    if not key: print("no key"); return
    print(f"PROBE store={sid}")

    # 1) Automation structure
    sc, au = get(f"{BASE}/v5/automations", key)
    autos = au.get("automations",[]) if isinstance(au,dict) else []
    print(f"[1] /v5/automations status={sc} count={len(autos)}")
    for a in autos[:4]:
        msgs = a.get("messages",[]) or []
        print(f"  AUTO id={a.get('id')} status={a.get('status')} trigger={a.get('trigger')!r} name={(a.get('name') or '')[:40]!r} msgs={len(msgs)} keys={list(a.keys())}")
        for m in msgs[:4]:
            print(f"     MSG keys={list(m.keys())} id={m.get('id')} channel={m.get('channel')} subject={(m.get('subject') or m.get('name') or '')[:30]!r}")
    auto_ids = set(a.get("id") for a in autos if a.get("id"))
    msg_ids  = set(m.get("id") for a in autos for m in (a.get("messages") or []) if m.get("id"))

    # 2) reports by marketingActivityID + extended metric discovery
    cand = ["sent","openRate","clickRate","attributedRevenue","attributedOrders","unsubscribeRate",
            "placedOrderRate","conversionRate","orderRate","revenue","placedOrders",
            "failedDeliveryRate","bounceRate","bounced","failedDelivery",
            "complaintRate","spamRate","markedAsSpamRate","complained",
            "opens","clicks","opened","clicked","delivered"]
    valid, rows = discover_metrics(key, d_from, d_to, ["marketingActivityID"], cand)
    print(f"[2] reports dim=marketingActivityID VALID_METRICS={valid}")
    print(f"    rows={len(rows)}")
    if rows:
        print(f"    sample row={json.dumps(rows[0])[:500]}")
        ids = [r.get('marketingActivityID') for r in rows]
        print(f"    match automation ids: {sum(1 for x in ids if x in auto_ids)}/{len(rows)} (autos={len(auto_ids)})")
        print(f"    match message ids:    {sum(1 for x in ids if x in msg_ids)}/{len(rows)} (msgs={len(msg_ids)})")

    # 3) per-flow per-channel breakdown (for Email/SMS drill-down)
    for chdim in ["marketingChannel","channel","messageChannel"]:
        sc, r = reports(key, d_from, d_to, ["marketingActivityID", chdim],
                        ["sent","openRate","clickRate","attributedRevenue"])
        if sc==200 and isinstance(r,dict):
            rr = (r.get("reports",[{}])[0]).get("rows",[])
            print(f"[3] dim=[marketingActivityID,{chdim}] OK rows={len(rr)} sample={json.dumps(rr[0])[:300] if rr else 'none'}")
        else:
            print(f"[3] dim=[marketingActivityID,{chdim}] status={sc} err={json.dumps(r)[:200] if isinstance(r,dict) else str(r)[:200]}")

    # 4) per-message dimension attempts
    for mdim in ["marketingActivityMessageID","messageID","marketingMessageID","automationMessageID"]:
        sc, r = reports(key, d_from, d_to, [mdim], ["sent","openRate"])
        ok = sc==200 and isinstance(r,dict)
        rr = (r.get("reports",[{}])[0]).get("rows",[]) if ok else []
        print(f"[4] dim={mdim} status={sc} rows={len(rr)} sample={json.dumps(rr[0])[:200] if rr else (json.dumps(r)[:160] if isinstance(r,dict) else '')}")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""TEMP probe — discover Omnisend FORM data & statistics. Prints logs only,
does not write index.html. Run on a throwaway branch."""
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

def get(url, key, params=None):
    try:
        r = requests.get(url, headers=hdrs(key), params=params, timeout=30)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    except Exception as e:
        return -1, str(e)

def post(url, key, payload):
    try:
        r = requests.post(url, headers=hdrs(key), json=payload, timeout=30)
        try: return r.status_code, r.json()
        except Exception: return r.status_code, r.text
    except Exception as e:
        return -1, str(e)

def reports(key, dfrom, dto, dims, metrics):
    return post(f"{BASE}/api/analytics/reports", key, {"queries":[{
        "alias":"q","dateRange":{"interval":"custom","from":dfrom,"to":dto},
        "dimensions":[{"name":d} for d in dims],
        "metrics":[{"name":m} for m in metrics]}]})

def discover(key, dfrom, dto, dims, cand):
    m=list(cand)
    for _ in range(len(cand)+1):
        sc,r=reports(key,dfrom,dto,dims,m)
        if sc==200:
            reps=r.get("reports",[]) if isinstance(r,dict) else []
            return m,(reps[0].get("rows",[]) if reps else [])
        bad=set()
        if isinstance(r,dict):
            for e in r.get("errors",[]):
                mm=re.search(r"metrics\[(\d+)\]",e.get("field",""))
                if mm: bad.add(int(mm.group(1)))
        if not bad:
            return None,r  # dimension error
        m=[x for i,x in enumerate(m) if i not in bad]
        if not m: return [],[]
    return m,[]

def main():
    now=datetime.now(timezone.utc)
    d_to=now.strftime("%Y-%m-%dT23:59:59Z")
    d_from=(now-timedelta(days=120)).strftime("%Y-%m-%dT00:00:00Z")
    key=sid=""
    for name,env in STORES:
        k=os.environ.get(env,"")
        if k: key,sid=k,name; break
    if not key: print("no key"); return
    print(f"PROBE store={sid}")

    # [1] /api/forms — full structure
    sc, f = get(f"{BASE}/api/forms", key, {"limit": 5})
    forms = f.get("forms",[]) if isinstance(f,dict) else []
    print(f"[1] /api/forms status={sc} count={len(forms)} paging={f.get('paging') if isinstance(f,dict) else ''}")
    if forms:
        print(f"    FORM0 full: {json.dumps(forms[0])[:900]}")
        for fo in forms[:5]:
            print(f"    form id={fo.get('id')} type={fo.get('type')} status={fo.get('status')} stats={json.dumps(fo.get('statistics'))[:200]}")
    fid = forms[0].get("id") if forms else None

    # [2] single form detail
    if fid:
        sc, d = get(f"{BASE}/api/forms/{fid}", key)
        print(f"[2] /api/forms/{fid} status={sc} keys={list(d.keys()) if isinstance(d,dict) else d} stats={json.dumps(d.get('statistics'))[:300] if isinstance(d,dict) else ''}")
        # try a statistics sub-resource
        for path in [f"/api/forms/{fid}/statistics", f"/v3/forms/{fid}/statistics"]:
            sc2,d2=get(f"{BASE}{path}", key)
            print(f"    {path} status={sc2} body={json.dumps(d2)[:200] if isinstance(d2,dict) else str(d2)[:120]}")

    # [3] analytics reports by a form dimension
    cand=["views","impressions","displayed","submissions","submitted","signups","subscribed",
          "conversionRate","submitRate","signupRate","interactionRate","subscribedEmail"]
    for dim in ["formID","formId","form","signupFormID","subscriptionFormID"]:
        m,rows=discover(key,d_from,d_to,[dim],cand)
        if m is None:
            print(f"[3] dim={dim} DIMENSION invalid")
        elif rows==[] and m==[]:
            print(f"[3] dim={dim} no valid metrics")
        else:
            print(f"[3] dim={dim} VALID_METRICS={m} rows={len(rows)} sample={json.dumps(rows[0])[:300] if rows else 'none'}")

    # [4] analytics statistics with form dimension (signups)
    for dim in ["formID","form"]:
        sc,r=post(f"{BASE}/api/analytics/statistics", key, {"queries":[{
            "alias":"q","dateRange":{"from":d_from,"to":d_to},
            "dimensions":[{"name":dim}],
            "metrics":[{"name":"subscribedEmail"}]}]})
        ok=sc==200 and isinstance(r,dict)
        rows=((r.get("statistics",[{}])[0]).get("rows",[]) if ok else [])
        print(f"[4] statistics dim={dim} status={sc} rows={len(rows)} sample={json.dumps(rows[0])[:200] if rows else (json.dumps(r)[:150] if isinstance(r,dict) else '')}")

if __name__=="__main__":
    main()

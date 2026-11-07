# -*- coding: utf-8 -*-
"""
给 dist/tvbox-sites.json 里的每个站点测一次「搜索」响应速度，产出 data/source_rank.json。

用途：build_home.py 按这份排名给自建源排序，让电视上的搜索结果里
快源排在前面，卡源排到最后，不用每次手动换。

用法：
    python scripts/rank_sources.py            # 测速并写 data/source_rank.json
    python scripts/rank_sources.py --show     # 只打印上次结果，不联网
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "dist", "tvbox-sites.json")
OUT = os.path.join(BASE, "data", "source_rank.json")

KEYWORD = "庆余年"
TIMEOUT = 8
WORKERS = 8

# 不走系统代理：采集站都在国内，直连最快
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
HEADERS = {
    "User-Agent": "okhttp/3.12.0",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "identity",
}


def fetch_json(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=HEADERS)
    with OPENER.open(req, timeout=timeout) as r:
        raw = r.read()
    # 有些站返回 GBK
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    return None


def probe(site):
    api = str(site.get("api", "")).strip()
    if not api:
        return {"ok": False, "ms": 99999, "results": 0, "note": "无 api"}

    base = api.rstrip("/")
    wd = urllib.parse.quote(KEYWORD)
    cands = [
        "%s/?ac=videolist&wd=%s&pagesize=1" % (base, wd),
        "%s?ac=videolist&wd=%s&pagesize=1" % (base, wd),
        "%s/?ac=detail&wd=%s&pagesize=1" % (base, wd),
        "%s?ac=detail&wd=%s&pagesize=1" % (base, wd),
    ]

    best = None
    for u in cands:
        t0 = time.time()
        try:
            d = fetch_json(u)
        except Exception as e:
            best = best or {"ok": False, "ms": int((time.time() - t0) * 1000),
                            "results": 0, "note": type(e).__name__}
            continue
        ms = int((time.time() - t0) * 1000)
        if isinstance(d, dict):
            lst = d.get("list")
            if isinstance(lst, list):
                return {"ok": True, "ms": ms, "results": len(lst), "note": ""}
            # 返回了 JSON 但没 list，通常是 ac 参数不对，继续试下一个
            best = {"ok": False, "ms": ms, "results": 0,
                    "note": "code=%s" % d.get("code")}
            continue
        best = {"ok": False, "ms": ms, "results": 0, "note": "非 JSON"}
    return best or {"ok": False, "ms": 99999, "results": 0, "note": "无响应"}


def load_sites():
    d = json.load(open(SRC, encoding="utf-8"))
    return d.get("sites", [])


def main():
    if "--show" in sys.argv:
        if not os.path.exists(OUT):
            print("还没有 %s，先跑一次测速" % OUT)
            return 0
        rank = json.load(open(OUT, encoding="utf-8"))
        for i, (k, v) in enumerate(
            sorted(rank.items(), key=lambda kv: _sort_key(kv[1])), 1
        ):
            print("%2d. %-24s %5sms  结果%-3s %s"
                  % (i, k, v.get("ms"), v.get("results"), v.get("note", "")))
        return 0

    sites = load_sites()
    print("开始测速：%d 个站点，关键词「%s」\n" % (len(sites), KEYWORD))

    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(probe, s): s for s in sites}
        for f in futs:
            pass
        for f, s in futs.items():
            k = str(s.get("key"))
            try:
                r = f.result()
            except Exception as e:
                r = {"ok": False, "ms": 99999, "results": 0, "note": str(e)}
            r["name"] = s.get("name")
            results[k] = r

    ordered = sorted(results.items(), key=lambda kv: _sort_key(kv[1]))
    for i, (k, v) in enumerate(ordered, 1):
        flag = "OK " if v["ok"] else "BAD"
        print("%2d. %-4s %-22s %5sms  结果%-3s %s"
              % (i, flag, str(v.get("name"))[:22], v.get("ms"),
                 v.get("results"), v.get("note", "")))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(results, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)

    ok = sum(1 for v in results.values() if v["ok"])
    print("\n可用 %d / %d，排名已写入 %s"
          % (ok, len(results), os.path.relpath(OUT, BASE)))
    return 0


def _sort_key(v):
    """快且能出结果排前面；失败的排最后"""
    return (0 if v.get("ok") else 1, v.get("ms") or 99999)


if __name__ == "__main__":
    sys.exit(main())

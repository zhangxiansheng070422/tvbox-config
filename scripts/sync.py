#!/usr/bin/env python3
"""TVBox 订阅合并器 —— 命令行版，供 GitHub Actions 或本机 cron 调用。

与本地容器里的 tvbox-sync 是同一套合并规则，区别只是不带 Web 界面：
  sources.txt → 逐个抓取 → 校验 JSON → 按 key 去重并进 api.json → 写回

用法：
    python scripts/sync.py            # 正常执行
    python scripts/sync.py --dry-run  # 只报告，不写文件

退出码：0 = 有源成功或无需处理；1 = 全部源失败（此时文件不动）
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_PATH = os.path.join(ROOT, "api.json")
SOURCES_PATH = os.path.join(ROOT, "sources.txt")
UA = "TVBox/2026 (+https://github.com)"
TIMEOUT = 20
MAX_BYTES = 8 * 1024 * 1024


def load_sources():
    if not os.path.exists(SOURCES_PATH):
        return []
    out, seen = [], set()
    with open(SOURCES_PATH, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(("http://", "https://")) or line in seen:
                continue
            seen.add(line)
            out.append(line)
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("响应超过 %d MB" % (MAX_BYTES // 1024 // 1024))
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace").lstrip("\ufeff")


def parse_source(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError("不是合法 JSON：第 %d 行 %s" % (e.lineno, e.msg))
    if not isinstance(data, dict):
        raise ValueError("顶层不是对象")
    if not any(k in data for k in ("sites", "lives", "parses", "spider")):
        raise ValueError("缺少 sites/lives/parses/spider，判断不是配置接口")
    return data


def key_of(item, fields):
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for f in fields:
            v = item.get(f)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return json.dumps(item, sort_keys=True, ensure_ascii=False)
    return str(item)


def union(base, new, fields):
    out, seen = [], set()
    for item in list(base or []) + list(new or []):
        k = key_of(item, fields)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def merge(base, incoming):
    merged = dict(base or {})
    before = (len(merged.get("sites") or []), len(merged.get("lives") or []),
              len(merged.get("parses") or []))
    merged["sites"] = union(merged.get("sites"), incoming.get("sites"), ("key", "name", "api"))
    merged["lives"] = union(merged.get("lives"), incoming.get("lives"), ("name", "url", "api"))
    merged["parses"] = union(merged.get("parses"), incoming.get("parses"), ("name", "url", "type"))
    after = (len(merged["sites"]), len(merged["lives"]), len(merged["parses"]))
    # spider 只在本地为空时采纳，避免被远端换掉
    if not merged.get("spider") and incoming.get("spider"):
        merged["spider"] = incoming["spider"]
    for k in ("flags", "ads"):
        if incoming.get(k) and not merged.get(k):
            merged[k] = incoming[k]
    return merged, {"sites_added": after[0] - before[0],
                    "lives_added": after[1] - before[1],
                    "parses_added": after[2] - before[2]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    urls = load_sources()
    if not urls:
        print("sources.txt 里没有可用地址，跳过本轮")
        return 0

    current = {}
    if os.path.exists(API_PATH):
        with open(API_PATH, encoding="utf-8-sig") as fh:
            current = json.load(fh)

    merged, report, ok_count = current, [], 0
    for url in urls:
        try:
            data = parse_source(fetch(url))
            merged, stats = merge(merged, data)
            ok_count += 1
            report.append("OK   %s  %s" % (url, stats))
        except urllib.error.HTTPError as e:
            report.append("FAIL %s  HTTP %s" % (url, e.code))
        except urllib.error.URLError as e:
            report.append("FAIL %s  连不上：%s" % (url, e.reason))
        except Exception as e:
            report.append("FAIL %s  %s: %s" % (url, type(e).__name__, e))

    print("\n".join(report))
    print("\n成功 %d / %d，站点 %d，直播 %d" %
          (ok_count, len(urls), len(merged.get("sites") or []), len(merged.get("lives") or [])))

    if ok_count == 0:
        print("全部失败，配置未改动")
        return 1

    changed = (json.dumps(current, sort_keys=True, ensure_ascii=False)
               != json.dumps(merged, sort_keys=True, ensure_ascii=False))
    if not changed:
        print("无变化，不写文件")
        return 0
    if args.dry_run:
        print("--dry-run：检测到变化，但未写入")
        return 0

    merged["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged["updatedBy"] = "github-actions"
    with open(API_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    print("已写入 api.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_PATH = os.path.join(ROOT, "api.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
SOURCES_PATH = os.path.join(ROOT, "sources.txt")
STATUS_PATH = os.path.join(ROOT, "sync-status.md")
STATUS_KEEP = 20
UA = "TVBox/2026 (+https://github.com)"
TIMEOUT = 20
MAX_BYTES = 8 * 1024 * 1024
CST = timezone(timedelta(hours=8))


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


def write_status(started, headline, detail, url_count, ok_count, merged):
    """把本轮结果写进 sync-status.md，让非程序员打开仓库就能看懂它跑没跑。"""
    sites = len(merged.get("sites") or [])
    lives = len(merged.get("lives") or [])
    stamp = started.astimezone(CST).strftime("%Y-%m-%d %H:%M")

    history = []
    if os.path.exists(STATUS_PATH):
        with open(STATUS_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("| 20") and line.count("|") >= 6:
                    history.append(line)
    new_row = "| %s | %s | %d/%d | %d | %d |" % (
        stamp, headline, ok_count, url_count, sites, lives)
    history = ([new_row] + history)[:STATUS_KEEP]

    note = {
        "skip": "**为什么一直是「跳过」**：`sources.txt` 里没有填任何地址，"
                "所以每 6 小时醒一次、看一眼、什么都没抓就回去了。"
                "在里面加一行 `https://...` 就会开始真正抓取。",
        "fail": "**全部源都抓不到**：`sources.txt` 里的地址可能失效或写错了，"
                "`api.json` 保持原样没有被改坏。",
        "same": "**抓到内容但和现有配置一样**：去重后没有新东西，所以不重复提交。",
        "done": "**本轮有新内容**：已经合并进 `api.json` 并自动提交。",
    }.get(detail, "")

    body = [
        "# 同步运行记录",
        "",
        "> 这个文件由 GitHub 的定时任务自动维护，每 6 小时更新一次。",
        "> 你不需要动它，看一眼就知道任务有没有在正常工作。",
        "",
        "## 最近一次",
        "",
        "- **运行时间**：%s（北京时间）" % stamp,
        "- **结果**：%s" % headline,
        "- **订阅清单**：%d 条地址，成功 %d 条" % (url_count, ok_count),
        "- **当前配置**：点播站点 %d 个，直播源 %d 个" % (sites, lives),
        "",
        note,
        "",
        "## 历史（最近 %d 次）" % STATUS_KEEP,
        "",
        "| 时间（北京） | 结果 | 成功/订阅 | 站点 | 直播 |",
        "| --- | --- | --- | --- | --- |",
    ] + history + [""]

    with open(STATUS_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    current = {}
    if os.path.exists(API_PATH):
        with open(API_PATH, encoding="utf-8-sig") as fh:
            current = json.load(fh)

    urls = load_sources()
    if not urls:
        print("sources.txt 里没有可用地址，跳过本轮")
        if not args.dry_run:
            write_status(started, "跳过：没有填订阅地址", "skip", 0, 0, current)
            print("已更新 sync-status.md")
        return 0

    merged, report, ok_count = current, [], 0
    report_sites = report_lives = 0
    for url in urls:
        try:
            data = parse_source(fetch(url))
            merged, stats = merge(merged, data)
            ok_count += 1
            report_sites += stats["sites_added"]
            report_lives += stats["lives_added"]
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
        if not args.dry_run:
            write_status(started, "失败：所有订阅地址都抓不到", "fail",
                         len(urls), 0, current)
        return 1

    changed = (json.dumps(current, sort_keys=True, ensure_ascii=False)
               != json.dumps(merged, sort_keys=True, ensure_ascii=False))
    if not changed:
        print("无变化，不写文件")
        if not args.dry_run:
            write_status(started, "完成：没有新内容", "same",
                         len(urls), ok_count, merged)
        return 0
    if args.dry_run:
        print("--dry-run：检测到变化，但未写入")
        return 0

    merged["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged["updatedBy"] = "github-actions"
    payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    # api.json 和 config.json 内容始终一致：
    # config.json 是电视端在用的地址（新路径，CDN 缓存更可靠），api.json 保留兼容。
    for path in (API_PATH, CONFIG_PATH):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
    print("已写入 api.json 与 config.json")
    write_status(started, "完成：已合并新内容（站点 +%d，直播 +%d）"
                 % (report_sites, report_lives), "done", len(urls), ok_count, merged)
    return 0


if __name__ == "__main__":
    sys.exit(main())

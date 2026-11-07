#!/usr/bin/env python3
"""公开直播源自动抓取器 —— 供 GitHub Actions 每 6 小时调用一次。

做的事：
  1. 从几个公开的 IPTV 列表项目拉最新频道清单（m3u）
  2. 只保留中文频道 / CCTV / CGTN，丢掉外语台和垃圾条目
  3. 同一频道的多条线路合并，最多留 3 条
  4. 逐条探测能否连通（IPv6 地址跳过探测，因为 GitHub 的机器没有 IPv6，
     探测会把好源误判成死源）
  5. 写入 sub/live_auto.txt

安全阀：如果这一轮可用频道少于 MIN_CHANNELS，认定是源站出问题或网络抖动，
保留原文件不动，绝不把用户正在用的清单清空。

用法：
    python scripts/sync_live.py
    python scripts/sync_live.py --no-probe     # 不探测，全部保留（本地调试用）
"""

import argparse
import concurrent.futures
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(ROOT, "sub", "live_auto.txt")
STATUS_PATH = os.path.join(ROOT, "live-status.md")

UA = "TVBox/2026 (+https://github.com)"
FETCH_TIMEOUT = 25
PROBE_TIMEOUT = 6
PROBE_WORKERS = 16
MIN_CHANNELS = 20
MAX_LINES_PER_CHANNEL = 3
STATUS_KEEP = 20
CST = timezone(timedelta(hours=8))

# 公开 IPTV 列表项目。都是公开仓库，内容为各电视台的公开直播流。
SOURCES = [
    ("央视频道·IPv6 线路", "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u"),
    ("中文频道总表", "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u"),
    ("移动/咪咕线路", "https://raw.githubusercontent.com/YanG-1989/m3u/main/Gather.m3u"),
]

BAD_WORDS = ("测试", "福利", "18+", "成人", "porn", "xxx", "广告", "购物",
             "轮播", "赛事", "游戏", "睛彩", "彩铃", "试看")

# 括号里的内容一律当注释丢掉：(1080p)、(576p) [Not 24/7]、【高清】……
BRACKET_RE = re.compile(r"[\[\(（【][^\]\)）】]*[\]\)）】]")
# 没有括号的分辨率后缀：CCTV-1 1080p
SUFFIX_RE = re.compile(r"\s+(?:\d{3,4}[piPI]|UHD|HD|SD|高清|超清|标清|蓝光|IPV6|备用\d*|线路\d*)\s*$")

GROUP_ORDER = ["央视频道", "卫视频道", "浙江频道", "其他频道"]

# 「其他频道」里只留名字像正规频道的，砍掉杂项
OTHER_OK = re.compile(r"频道|电视台|TV|台$")
CCTV_RE = re.compile(r"^CCTV[-\s]?(\d{1,2}\+?|4K|8K)", re.I)


def fetch(url, attempts=3):
    last = None
    for i in range(attempts):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
                return resp.read().decode("utf-8", errors="replace").lstrip("\ufeff")
        except Exception as e:      # 网络抖动、代理断流都重试
            last = e
            if i + 1 < attempts:
                time.sleep(2 * (i + 1))
    raise last


def parse_m3u(text):
    """从 m3u 里取出 (频道名, 分组, 地址)。不依赖 #EXTM3U 头。"""
    lines = [l.strip() for l in text.splitlines()]
    out = []
    for i, line in enumerate(lines):
        if not line.startswith("#EXTINF"):
            continue
        name = line.rsplit(",", 1)[-1].strip() if "," in line else ""
        g = re.search(r'group-title="([^"]*)"', line)
        url = ""
        for j in range(i + 1, min(i + 5, len(lines))):
            nxt = lines[j]
            if nxt and not nxt.startswith("#"):
                url = nxt
                break
        if name and url.startswith("http"):
            out.append((name, g.group(1) if g else "", url))
    return out


def clean_name(name):
    n = name.replace("\u200b", "").replace("\xa0", " ").strip()
    n = BRACKET_RE.sub("", n)                    # (1080p) [Not 24/7] 这类注解
    n = re.sub(r"^(?:BRTV|BTV|CNTV)\s+", "", n)  # 台标缩写，留着反而乱
    n = re.sub(r"\s+", " ", n).strip()
    for _ in range(2):
        trimmed = SUFFIX_RE.sub("", n).strip()
        if trimmed == n:
            break
        n = trimmed
    return n or "未命名"


def natural_key(s):
    """让 CCTV-1 排在 CCTV-10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def canon(name):
    """归并键：把「CCTV-1」「CCTV1」「CCTV-1综合」认成同一个频道。"""
    s = name.strip()
    m = CCTV_RE.match(s)
    if m:
        return "cctv-" + m.group(1).lower()
    s = re.sub(r"^(?:BRTV|BTV|北京广播电视台)\s*", "", s)
    return s


def wanted(name):
    """只要中文频道、央视和 CGTN。外语台对这套配置没意义。"""
    if any(b in name for b in BAD_WORDS):
        return False
    if re.search(r"[\u4e00-\u9fff]", name):
        return True
    return bool(re.search(r"(?i)\bcctv\b|cgtn", name))


def classify(name, group):
    if re.search(r"(?i)\bcctv\b|cgtn", name) or "央视" in group:
        return "央视频道"
    if "卫视" in name or "卫视" in group:
        return "卫视频道"
    if "浙江" in name or "浙江" in group:
        return "浙江频道"
    return "其他频道"


def is_ipv6(url):
    return bool(re.match(r"^https?://\[", url))


def probe(url):
    """能否连上。IPv6 直接放行，原因见文件头注释。"""
    if is_ipv6(url):
        return True
    req = urllib.request.Request(url, headers={"User-Agent": "okhttp/3.12"},
                                 method="GET")
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            resp.read(2048)
            return resp.status in (200, 206)
    except Exception:
        return False


def load_previous():
    """读上一版输出，用于源站抖动时兜底。"""
    prev = {}
    if not os.path.exists(OUT_PATH):
        return prev
    cur = None
    with open(OUT_PATH, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith(",#genre#"):
                cur = line[:-8]
                continue
            if cur is None:
                continue
            parts = line.split(",")
            urls = [u for u in parts[1:] if u.startswith("http")]
            if parts[0] and urls:
                prev[(cur, canon(parts[0]))] = (parts[0], urls)
    return prev


def build(items, prev, do_probe, keep_missing):
    """归并 → 探测 → 返回 {分组: {频道名: [线路...]}} 与统计。

    探测结果只用来**排序**（能连的排前面），不用来删源：
    GitHub 的机器在境外，对国内许多直播源判断不准，误杀比留死链更糟。
    """
    urls_of, display = {}, {}
    for raw_name, group, url in items:
        name = clean_name(raw_name)
        if not wanted(name):
            continue
        grp = classify(name, group)
        if grp == "其他频道" and not OTHER_OK.search(name):
            continue
        key = (grp, canon(name))
        urls_of.setdefault(key, [])
        if url not in urls_of[key]:
            urls_of[key].append(url)
        # 显示名用信息最全的那个：CCTV-1综合 优于 CCTV-1
        if key not in display or len(name) > len(display[key]):
            display[key] = name

    total_urls = sum(len(v) for v in urls_of.values())

    alive = set()
    if do_probe:
        flat = [(k, u) for k, urls in urls_of.items() for u in urls]
        with concurrent.futures.ThreadPoolExecutor(max_workers=PROBE_WORKERS) as ex:
            futures = {ex.submit(probe, u): (k, u) for k, u in flat}
            for fut in concurrent.futures.as_completed(futures):
                key, u = futures[fut]
                try:
                    if fut.result():
                        alive.add((key, u))
                except Exception:
                    pass

    kept = {}
    for key, urls in urls_of.items():
        good = [u for u in urls if (key, u) in alive]
        bad = [u for u in urls if (key, u) not in alive]
        kept[key] = (good + bad)[:MAX_LINES_PER_CHANNEL]

    if keep_missing:
        for key, (name, urls) in prev.items():
            if key not in kept:
                kept[key] = urls[:MAX_LINES_PER_CHANNEL]
                display.setdefault(key, name)

    rows = {g: [] for g in GROUP_ORDER}
    for (grp, key), urls in kept.items():
        # 组内排序：有线路连得上的排前面，全连不上的沉底
        alive_flag = 0 if any((key, u) in alive for u in urls) else 1
        rows[grp].append((alive_flag, display[(grp, key)], urls))

    grouped = {}
    for g in GROUP_ORDER:
        ordered = sorted(rows[g], key=lambda r: (r[0], natural_key(r[1])))
        grouped[g] = {name: urls for _, name, urls in ordered}
    return grouped, total_urls


def render(grouped):
    lines = [
        "# 自动抓取的公开直播源",
        "# 由 GitHub Actions 每 6 小时更新一次，请勿手工编辑",
        "# 格式：分组名,#genre# ；频道名,线路1,线路2",
        "",
    ]
    channels = 0
    for g in GROUP_ORDER:
        if not grouped.get(g):
            continue
        lines.append(g + ",#genre#")
        for name, urls in grouped[g].items():
            lines.append(name + "," + ",".join(urls))
            channels += 1
        lines.append("")
    return "\n".join(lines), channels


def write_status(started, headline, detail, channel_count, kept_urls, fetched_urls):
    stamp = started.astimezone(CST).strftime("%Y-%m-%d %H:%M")
    history = []
    if os.path.exists(STATUS_PATH):
        with open(STATUS_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("| 20") and line.count("|") >= 5:
                    history.append(line)
    row = "| %s | %s | %d | %d |" % (stamp, headline, channel_count, kept_urls)
    history = ([row] + history)[:STATUS_KEEP]

    note = {
        "ok": "**本轮抓到了新清单**：`sub/live_auto.txt` 已更新并自动提交，"
              "电视端下次加载配置就能看到。",
        "keep": "**本轮可用频道太少，判定为源站异常**，保留上一版清单没有覆盖，"
                "等下一轮再试。",
        "fail": "**所有源都抓不到**（可能是 GitHub 网络抖动），保留上一版清单。",
    }.get(detail, "")

    body = [
        "# 直播源自动抓取记录",
        "",
        "> 这个文件由 GitHub 的定时任务自动维护，每 6 小时更新一次。",
        "> 它只负责 `sub/live_auto.txt`（自动抓来的公开频道），",
        "> 不碰 `sub/live.txt`（那份是精挑过、逐台实测过的手工清单）。",
        "",
        "## 最近一次",
        "",
        "- **运行时间**：%s（北京时间）" % stamp,
        "- **结果**：%s" % headline,
        "- **频道数**：%d 个" % channel_count,
        "- **线路数**：%d 条（本轮新抓到 %d 条，其余是上一版留存的备用线路）"
        % (kept_urls, fetched_urls),
        "",
        note,
        "",
        "## 历史（最近 %d 次）" % STATUS_KEEP,
        "",
        "| 时间（北京） | 结果 | 频道 | 线路 |",
        "| --- | --- | --- | --- |",
    ] + history + [""]

    with open(STATUS_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-probe", action="store_true", help="跳过连通性探测")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    items, ok_src = [], 0
    for label, url in SOURCES:
        try:
            got = parse_m3u(fetch(url))
            items.extend(got)
            ok_src += 1
            print("OK   %-18s %d 条  %s" % (label, len(got), url))
        except urllib.error.HTTPError as e:
            print("FAIL %-18s HTTP %s  %s" % (label, e.code, url))
        except Exception as e:
            print("FAIL %-18s %s: %s  %s" % (label, type(e).__name__, e, url))

    if ok_src == 0:
        print("全部源都抓不到，保留原文件")
        write_status(started, "失败：所有源都抓不到", "fail", 0, 0, 0)
        return 0

    prev = load_previous()
    # 有源没抓到时，按「只增不减」处理，避免源站抖动把电视上的台抹掉
    keep_missing = ok_src < len(SOURCES)
    grouped, total_urls = build(items, prev, not args.no_probe, keep_missing)
    text, channels = render(grouped)
    kept_urls = sum(len(u) for g in grouped.values() for u in g.values())

    print("原始条目 %d → 频道 %d，线路 %d%s"
          % (len(items), channels, kept_urls,
             "  ｜源不齐，只增不减" if keep_missing else ""))

    if channels < MIN_CHANNELS:
        print("可用频道 %d 个，低于下限 %d，保留原文件不覆盖" % (channels, MIN_CHANNELS))
        write_status(started, "跳过：可用频道太少，保留上一版", "keep",
                     channels, kept_urls, total_urls)
        return 0

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("已写入 %s" % os.path.relpath(OUT_PATH, ROOT))

    write_status(started, "完成：已更新自动清单", "ok", channels, kept_urls, total_urls)
    return 0


if __name__ == "__main__":
    sys.exit(main())

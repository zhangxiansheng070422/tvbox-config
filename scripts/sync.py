#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TVBox 订阅合并器 —— 供 GitHub Actions 每 6 小时调用一次。

它做的四件事：
  1. 读 sources.txt 里的地址，抓回来（支持两种写法：直接的配置 JSON；
     或者是"地址清单"，清单里再列多个配置地址，会自动展开一层）
  2. 校验抓回来的是不是合法配置，按 key / api / name 去重后合并
  3. 写回 config.json 与 api.json（两个文件内容永远一致）
  4. 探测每个点播站点的接口还活着没有，写进 vod-status.md

另外会把 sites/ 目录下的 *.json 本地片段一起并入，
想手工补几个站点，直接往那个目录放文件就行，不用改脚本。

用法：
    python scripts/sync.py                # 正常执行
    python scripts/sync.py --dry-run      # 只报告，不写文件
    python scripts/sync.py --no-probe     # 跳过站点存活探测（快）
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")     # 电视端在用的主入口
API_PATH = os.path.join(ROOT, "api.json")           # 保留兼容的旧路径
SOURCES_PATH = os.path.join(ROOT, "sources.txt")
FRAGMENT_DIR = os.path.join(ROOT, "sites")          # 本地站点片段目录
STATUS_PATH = os.path.join(ROOT, "sync-status.md")
VOD_PATH = os.path.join(ROOT, "vod-status.md")

STATUS_KEEP = 20
UA = "TVBox/2026 (+https://github.com/zhangxiansheng070422/tvbox-config)"
TIMEOUT = 20
MAX_BYTES = 8 * 1024 * 1024
INDEX_MAX = 20        # 一个文本清单最多展开 20 条，防止被喂几千条把 runner 跑满
MULTI_MAX = 40        # 一个多仓最多取 40 个子接口
INDEX_DEPTH = 2       # 清单套清单最多两层
PROBE_TIMEOUT = 8
PROBE_WORKERS = 6
PROBE_MAX = 60        # 一次最多探测 60 个站点，再多就分轮
CST = timezone(timedelta(hours=8))
URL_RE = re.compile(r"https?://[^\s\"'<>\\,;]+")


# ---------------------------------------------------------------- 抓取

TRIM_TAIL = "，。；、）)】」》\"'"
# 资源闸门：清单动辄上千条，全抓会把 runner 跑爆（Actions 有 6 小时硬超时）。
# 这里按「同一域名最多 2 条 + 总数上限 + 总耗时上限」三重限制，
# 超出部分不报错，只在日志和状态页里说明被略过了多少条。
MAX_SOURCES = int(os.environ.get("TVBOX_MAX_SOURCES", "120"))
PER_HOST_MAX = 2
FETCH_BUDGET = int(os.environ.get("TVBOX_FETCH_BUDGET", "600"))


def load_sources():
    """从 sources.txt 里把地址抠出来。

    允许两种写法：
      http://a.com/x                —— 纯地址
      饭太硬：http://a.com/x 备用    —— 带中文名称/备注
    只要行里出现 http(s):// 就收下，一格里有多条也全收。
    以 # 开头的整行忽略（备注用）。
    """
    if not os.path.exists(SOURCES_PATH):
        return [], 0
    raw, seen = [], set()
    with open(SOURCES_PATH, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for m in URL_RE.findall(line):
                m = m.strip().rstrip(TRIM_TAIL)
                if not m or m in seen:
                    continue
                seen.add(m)
                raw.append(m)

    # 同一域名最多留 2 条：清单里常见一个域名挂几十个变体，抓完也没有新站点
    per_host, out = {}, []
    for u in raw:
        try:
            host = urllib.parse.urlsplit(normalize_url(u)).hostname or u
        except Exception:
            host = u
        if per_host.get(host, 0) >= PER_HOST_MAX:
            continue
        per_host[host] = per_host.get(host, 0) + 1
        out.append(u)

    skipped = len(raw) - min(len(out), MAX_SOURCES)
    return out[:MAX_SOURCES], skipped


def normalize_url(url):
    """把地址规范成 urllib 能发出去的形式。

    两个坑：中文域名（www.饭太硬.com）必须先转 punycode，否则 http.client
    在编码 host 时直接抛 UnicodeEncodeError；路径里的中文要百分号编码。
    """
    try:
        p = urllib.parse.urlsplit(url.strip())
        host = p.hostname or ""
        if not host:
            return url
        try:
            host.encode("ascii")
            ascii_host = host
        except UnicodeEncodeError:
            ascii_host = host.encode("idna").decode("ascii")
        netloc = ascii_host
        if p.port:
            netloc += ":%d" % p.port
        if p.username:
            cred = p.username
            if p.password:
                cred += ":" + p.password
            netloc = cred + "@" + netloc
        path = urllib.parse.quote(p.path or "/", safe="/%:@&=+$,~!*'()")
        query = urllib.parse.quote(p.query, safe="=&?/:@+$,%~-_.!*'()")
        return urllib.parse.urlunsplit((p.scheme, netloc, path, query, p.fragment))
    except Exception:
        return url


def fetch_text(url):
    url = normalize_url(url)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",      # 尽量绕过中间层缓存，拿到最新一版
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
    if isinstance(data, list):
        # 有些人的配置顶层直接给一个站点数组，宽容地包一层
        data = {"sites": data}
    if not isinstance(data, dict):
        raise ValueError("顶层既不是对象也不是数组")
    if "sites" not in data and isinstance(data.get("api_site"), dict):
        # LunaTV 一类配置的写法：{"api_site": {"域名": {"name":..,"api":..}}}
        # 里面装的就是一堆 CMS 采集接口，转成 TVBox 的 sites 数组
        data["sites"] = sites_from_api_site(data["api_site"])
    if not any(k in data for k in ("sites", "lives", "parses", "spider")):
        raise ValueError("缺少 sites/lives/parses/spider，判断不是配置接口")
    return data


def sites_from_api_site(mapping):
    out, used = [], set()
    for domain, info in mapping.items():
        if not isinstance(info, dict):
            continue
        api = info.get("api") or ("https://%s/api.php/provide/vod" % domain)
        if not api.startswith(("http://", "https://")):
            continue
        key = re.sub(r"[^a-z0-9]", "", str(domain).lower())[:24] or "cms"
        base, n = key, 1
        while key in used:
            n += 1
            key = "%s%d" % (base[:20], n)
        used.add(key)
        site = {
            "key": key,
            "name": info.get("name") or domain,
            "type": 1,
            "api": api,
            "searchable": 1,
            "quickSearch": 1,
            "filterable": 0,
        }
        out.append(site)
    return out


B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(text):
    """Base58 解码。有些源故意把 JSON 转成 Base58 再发布，防止直接抄。"""
    n = 0
    for ch in text:
        idx = B58_ALPHABET.find(ch)
        if idx < 0:
            raise ValueError("不是 Base58")
        n = n * 58 + idx
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(text) - len(text.lstrip("1"))) + raw


def try_decode_wrapped(text):
    """正文不是 JSON 时，试一下 Base58；解出来是 JSON 就返回它。"""
    s = text.strip()
    if len(s) < 40 or len(s) > 4 * 1024 * 1024:
        return None
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]+", s):
        return None
    try:
        raw = b58decode(s)
        decoded = raw.decode("utf-8")
    except Exception:
        return None
    return decoded if decoded.lstrip()[:1] in ("{", "[") else None


def describe(e):
    if isinstance(e, urllib.error.HTTPError):
        return "HTTP %s" % e.code
    if isinstance(e, urllib.error.URLError):
        return "连不上：%s" % (e.reason,)
    return "%s: %s" % (type(e).__name__, e)


def extract_urls(data):
    """多仓格式 {"urls":[{"url":..,"name":..}]} → 里面的子接口地址。

    多仓顶层没有 sites/lives，直接当配置会被判成非法，所以先拆一层。
    """
    items = data.get("urls") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for it in items:
        u = it.get("url") if isinstance(it, dict) else it
        if isinstance(u, str) and u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def expand(url, depth=0, seen=None, out=None):
    """抓一个地址。是配置就收下；是纯文本清单或多仓就把里面的地址继续展开。

    返回 [{"url":..., "ok":bool, "data"/"error":...}]
    """
    seen = seen if seen is not None else set()
    out = out if out is not None else []
    if url in seen:
        return out
    if depth > INDEX_DEPTH:
        out.append({"url": url, "ok": False, "error": "嵌套太深，跳过"})
        return out
    seen.add(url)

    try:
        text = fetch_text(url)
    except Exception as e:
        out.append({"url": url, "ok": False, "error": describe(e)})
        return out

    head = text.lstrip()[:1]
    if head not in ("{", "["):
        wrapped = try_decode_wrapped(text)
        if wrapped is not None:
            print("   %s 是 Base58 编码，已解出配置" % url)
            text, head = wrapped, "{"
    if head in ("{", "["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            out.append({"url": url, "ok": False,
                        "error": "不是合法 JSON：第 %d 行 %s" % (e.lineno, e.msg)})
            return out

        kids = extract_urls(data)
        if kids:
            if len(kids) > MULTI_MAX:
                print("   %s 是多仓，共 %d 个子接口，只取前 %d 个"
                      % (url, len(kids), MULTI_MAX))
                kids = kids[:MULTI_MAX]
            else:
                print("   %s 是多仓，展开 %d 个子接口" % (url, len(kids)))
            for k in kids:
                expand(k, depth + 1, seen, out)
            return out

        try:
            out.append({"url": url, "ok": True, "data": parse_source(text)})
        except ValueError as e:
            out.append({"url": url, "ok": False, "error": str(e)})
        return out

    # 不是 JSON —— 当成文本清单，把里面的地址再抓一轮
    kids = []
    for m in URL_RE.findall(text):
        m = m.rstrip(".,;)\"'")
        if m not in seen and m not in kids:
            kids.append(m)
    if not kids:
        out.append({"url": url, "ok": False,
                    "error": "既不是 JSON，里面也没找到别的地址"})
        return out
    if len(kids) > INDEX_MAX:
        out.append({"url": url, "ok": False,
                    "error": "清单里有 %d 条地址，只展开前 %d 条" % (len(kids), INDEX_MAX)})
        kids = kids[:INDEX_MAX]
    for k in kids:
        expand(k, depth + 1, seen, out)
    return out


def load_fragments():
    """读 sites/ 目录下的本地片段，格式同配置：{"sites":[...]} 或直接 [...]。"""
    frags = []
    if not os.path.isdir(FRAGMENT_DIR):
        return frags
    for name in sorted(os.listdir(FRAGMENT_DIR)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(FRAGMENT_DIR, name)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                data = {"sites": data}
            if isinstance(data, dict):
                frags.append((os.path.join("sites", name), data))
        except Exception as e:
            print("片段读取失败 %s：%s" % (name, e))
    return frags


# ---------------------------------------------------------------- 合并

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


def looks_adult(site):
    """成人向站点不进配置。远端清单里常混着这类，别让它在电视上弹出来。"""
    if not isinstance(site, dict):
        return False
    name = str(site.get("name") or "")
    return any(m in name for m in ("🔞", "18+", "18＋", "成人", "里番", "无码"))


# 不做进配置的站点类别：教育（小学/初中/高中）、戏曲、音乐、哔哩、观影、短剧。
# 匹配站点名，大小写不敏感；命中的站点在合并阶段直接丢弃。
EXCLUDE_WORDS = (
    "小学", "初中", "高中", "中小学", "幼儿", "早教", "智教", "教育",
    "戏曲", "戏剧", "京剧", "越剧",
    "音乐", "听歌", "歌曲", "MV",
    "哔哩", "bilibili", "b站",
    "观影",
    "短剧",
)


def excluded_reason(site):
    """命中 EXCLUDE_WORDS 就返回命中的那个词，否则返回 None。"""
    if not isinstance(site, dict):
        return None
    name = str(site.get("name") or "").lower()
    for w in EXCLUDE_WORDS:
        if w.lower() in name:
            return w
    return None


def merge(base, incoming, allow_lives=False):
    """把 incoming 并进 base。只增不删。

    allow_lives=False 时不动本地直播配置 —— 抓点播不该把辛苦调好的台序打乱。
    spider 不从远端采纳：它是会下载执行的 jar，来源不明的不要。
    """
    merged = dict(base or {})
    before = (len(merged.get("sites") or []), len(merged.get("lives") or []),
              len(merged.get("parses") or []))
    new_sites = list(incoming.get("sites") or [])
    kept = []
    drop_adult = 0
    drop_cat = {}
    for s in new_sites:
        if looks_adult(s):
            drop_adult += 1
            continue
        why = excluded_reason(s)
        if why:
            drop_cat[why] = drop_cat.get(why, 0) + 1
            continue
        kept.append(s)
    if drop_adult:
        print("   （已拦下 %d 个成人向站点，不加进配置）" % drop_adult)
    if drop_cat:
        detail = "、".join("%s×%d" % (k, v) for k, v in drop_cat.items())
        print("   （按类别剔除 %d 个站点：%s）" % (sum(drop_cat.values()), detail))
    merged["sites"] = union(merged.get("sites"), kept, ("key", "api", "name"))
    if allow_lives or not merged.get("lives"):
        merged["lives"] = union(merged.get("lives"), incoming.get("lives"),
                                ("name", "url", "api"))
    merged["parses"] = union(merged.get("parses"), incoming.get("parses"),
                             ("name", "url", "type"))
    after = (len(merged["sites"]), len(merged["lives"]), len(merged["parses"]))
    if not merged.get("spider") and incoming.get("spider"):
        print("   （远端带了 spider，未采纳：来源不明的 jar 不自动加载）")
    for k in ("flags", "ads", "wallpaper", "logo"):
        if incoming.get(k) and not merged.get(k):
            merged[k] = incoming[k]
    return merged, {"sites_added": after[0] - before[0],
                    "lives_added": after[1] - before[1],
                    "parses_added": after[2] - before[2]}


# ---------------------------------------------------------------- 站点探测

def probe_target(site):
    """能探就返回要请求的地址，探不了（spider / 没写 api）返回 None。"""
    if not isinstance(site, dict):
        return None
    api = (site.get("api") or "").strip()
    if not api.startswith(("http://", "https://")):
        return None
    if str(site.get("type")) == "3":      # spider 类型，要靠客户端插件，外面探不到
        return None
    return api


def probe_one(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Range": "bytes=0-2047",
    })
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            resp.read(2048)
            return "ok", "HTTP %s" % resp.status
    except urllib.error.HTTPError as e:
        # 403/404 多半是要求带参数，域名其实是活的；5xx 就是服务端挂了
        if e.code < 500:
            return "warn", "HTTP %s" % e.code
        return "bad", "HTTP %s" % e.code
    except Exception:
        return "bad", "连不上"


def probe_sites(sites):
    """并发探测，返回 {站点下标: (状态, 说明)}。同一个地址只探一次。"""
    targets, index = {}, []
    for i, s in enumerate(sites):
        u = probe_target(s)
        if not u:
            index.append((i, None))
            continue
        index.append((i, u))
        targets.setdefault(u, None)

    urls = list(targets)[:PROBE_MAX]
    if urls:
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            for u, res in zip(urls, pool.map(probe_one, urls)):
                targets[u] = res
        # 超出上限的按「未探测」处理，避免一轮跑太久
        for u in list(targets):
            if u not in urls:
                targets[u] = ("skip", "本轮未探测（数量上限）")

    result = {}
    for i, u in index:
        if u is None:
            result[i] = ("skip", "spider 或没写接口地址，需客户端插件")
        else:
            result[i] = targets.get(u, ("skip", "本轮未探测"))
    return result


# ---------------------------------------------------------------- 状态页

def read_history(path, min_cols):
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("| 20") and line.count("|") >= min_cols:
                    rows.append(line)
    return rows


def write_status(started, headline, detail, url_count, ok_count, merged):
    """把本轮结果写进 sync-status.md，让非程序员打开仓库就能看懂它跑没跑。"""
    sites = len(merged.get("sites") or [])
    lives = len(merged.get("lives") or [])
    stamp = started.astimezone(CST).strftime("%Y-%m-%d %H:%M")

    new_row = "| %s | %s | %d/%d | %d | %d |" % (
        stamp, headline, ok_count, url_count, sites, lives)
    history = ([new_row] + read_history(STATUS_PATH, 6))[:STATUS_KEEP]

    note = {
        "skip": "**为什么一直是「跳过」**：`sources.txt` 里没有填任何地址，"
                "所以每 6 小时醒一次、看一眼、什么都没抓就回去了。"
                "在里面加一行 `https://...` 就会开始真正抓取，"
                "加进去以后不用再管，它会自己一直跑。",
        "fail": "**全部源都抓不到**：`sources.txt` 里的地址可能失效或写错了。"
                "配置保持原样，没有被改坏。",
        "same": "**抓到内容但和现有配置一样**：去重后没有新东西，所以不重复提交。",
        "done": "**本轮有新内容**：已经合并进 `config.json` 并自动提交。"
                "电视端重新加载一次配置就能看到。",
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
        "站点活着没有、哪个连不上，看同目录的 **`vod-status.md`**。",
        "",
        "## 历史（最近 %d 次）" % STATUS_KEEP,
        "",
        "| 时间（北京） | 结果 | 成功/订阅 | 站点 | 直播 |",
        "| --- | --- | --- | --- | --- |",
    ] + history + [""]

    with open(STATUS_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(body))


VOD_HEAD = [
    "# 点播站点状态",
    "",
    "> 由 GitHub 定时任务自动维护，每 6 小时更新一次。",
    "> 「正常」= 接口连得上；「待观察」= 接口回了 403/404（多半要求带参数，一般还活着）；",
    "> 「连不上」= 域名或网络不通，这个站点在电视端多半点不开。",
    "",
]


def write_vod_status(merged, probes, note=None):
    sites = merged.get("sites") or []
    stamp = datetime.now(CST).strftime("%Y-%m-%d %H:%M")

    if not sites:
        body = VOD_HEAD[:1] + [
            "",
            "> 由 GitHub 定时任务自动维护，每 6 小时更新一次。",
            "",
            "## 现在还没有点播源",
            "",
            "`config.json` 里的 `sites` 是空的，所以电视端点进去只有直播、没有点播片库。",
            "",
            "让点播出现内容只有一个开关：仓库根目录的 **`sources.txt`**。",
            "",
            "1. 在 GitHub 网页上打开 `sources.txt` → 点右上角铅笔图标",
            "2. 在末尾加一行你有的配置地址（`https://` 开头，返回 JSON 的那种）",
            "3. 拉到下面点 `Commit changes`",
            "4. 去 Actions 页面点一次 `Run workflow`（或者等最多 6 小时），它会自动抓取、合并、提交",
            "5. 电视端重新加载一次配置，点播区就有内容了",
            "",
            "> 加进去以后就不用再管了：只要那个地址还在更新，你的配置就跟着自动更新。",
            "> 地址失效也不会把已有配置改坏，只会停在上一版。",
            "",
        ]
        if note:
            body += ["## 本轮结果", "", note, ""]
        _write(VOD_PATH, body)
        return

    counts = {"ok": 0, "warn": 0, "bad": 0, "skip": 0}
    rows = []
    for i, s in enumerate(sites):
        if isinstance(s, dict):
            name = str(s.get("name") or s.get("key") or "未命名")
            kind = str(s.get("type", "")) or "-"
            api = str(s.get("api") or "")
        else:
            name, kind, api = str(s)[:40], "-", ""
        state, why = probes.get(i, ("skip", "未探测"))
        counts[state] = counts.get(state, 0) + 1
        icon = {"ok": "正常", "warn": "待观察", "bad": "连不上", "skip": "未探测"}[state]
        host = ""
        if api.startswith(("http://", "https://")):
            host = api.split("://", 1)[1].split("/", 1)[0]
        rows.append("| %s | %s | %s | %s | %s |" % (
            name.replace("|", "/"), kind, icon, why.replace("|", "/"), host or "—"))

    body = VOD_HEAD + [
        "## 概况",
        "",
        "- **检查时间**：%s（北京时间）" % stamp,
        "- **点播站点**：%d 个（正常 %d / 待观察 %d / 连不上 %d / 未探测 %d）" % (
            len(sites), counts["ok"], counts["warn"], counts["bad"], counts["skip"]),
        "",
        "## 明细",
        "",
        "| 站点 | 类型 | 状态 | 说明 | 接口域名 |",
        "| --- | --- | --- | --- | --- |",
    ] + rows + [
        "",
        "## 怎么让它自动更新",
        "",
        "站点来自 `sources.txt` 里的地址（外加 `sites/` 目录下的本地片段）。",
        "在 `sources.txt` 里加一行、提交，剩下的抓取/合并/去重/提交都是自动的。",
        "地址失效只会让对应站点变成「连不上」，不会把整个配置改坏。",
        "",
    ]
    _write(VOD_PATH, body)


def _write(path, lines):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------- 主流程

def load_current():
    for path in (CONFIG_PATH, API_PATH):
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as fh:
                try:
                    return json.load(fh), path
                except json.JSONDecodeError:
                    print("警告：%s 不是合法 JSON，已忽略" % os.path.basename(path))
    return {}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--allow-lives", action="store_true",
                    help="允许远端配置覆盖本地直播列表（默认不覆盖）")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    current, src = load_current()
    print("基准配置：%s（站点 %d，直播 %d）" % (
        os.path.basename(src) if src else "无",
        len(current.get("sites") or []), len(current.get("lives") or [])))

    urls, skipped = load_sources()
    frags = load_fragments()
    if urls:
        print("sources.txt 提取到地址 %d 条%s" % (
            len(urls),
            "（另有 %d 条因单域名上限/总量上限略过）" % skipped if skipped else ""))
    if not urls and not frags:
        print("sources.txt 里没有地址，sites/ 里也没有片段，跳过本轮")
        if not args.dry_run:
            write_status(started, "跳过：没有填订阅地址", "skip", 0, 0, current)
            write_vod_status(current, {}, note="本轮没有可抓的地址。")
            print("已更新 sync-status.md / vod-status.md")
        return 0

    results = []
    deadline = time.time() + FETCH_BUDGET
    stopped_early = 0
    for i, u in enumerate(urls):
        if time.time() > deadline:
            stopped_early = len(urls) - i
            print("已达抓取时限 %d 秒，剩余 %d 条本轮不再抓" % (FETCH_BUDGET, stopped_early))
            break
        expand(u, 0, set(), results)

    merged, ok_count, adds = current, 0, {"sites_added": 0, "lives_added": 0}
    report = []
    for r in results:
        if r["ok"]:
            merged, stats = merge(merged, r["data"], allow_lives=args.allow_lives)
            ok_count += 1
            adds["sites_added"] += stats["sites_added"]
            adds["lives_added"] += stats["lives_added"]
            report.append("OK   %s  +%d 站点 +%d 直播" % (
                r["url"], stats["sites_added"], stats["lives_added"]))
        else:
            report.append("FAIL %s  %s" % (r["url"], r["error"]))

    for name, data in frags:
        merged, stats = merge(merged, data, allow_lives=args.allow_lives)
        ok_count += 1
        adds["sites_added"] += stats["sites_added"]
        adds["lives_added"] += stats["lives_added"]
        report.append("OK   本地片段 %s  +%d 站点" % (name, stats["sites_added"]))

    print("\n".join(report))
    total = len(results) + len(frags)
    print("\n成功 %d / %d，站点 %d，直播 %d" % (
        ok_count, total, len(merged.get("sites") or []), len(merged.get("lives") or [])))

    if total and ok_count == 0:
        print("全部失败，配置未改动")
        if not args.dry_run:
            write_status(started, "失败：所有订阅地址都抓不到", "fail",
                         total, 0, current)
            write_vod_status(current, {}, note="本轮所有地址都抓不到，配置保持原样。")
        return 1

    probes = {} if args.no_probe else probe_sites(merged.get("sites") or [])

    changed = (json.dumps(current, sort_keys=True, ensure_ascii=False)
               != json.dumps(merged, sort_keys=True, ensure_ascii=False))

    if args.dry_run:
        print("--dry-run：%s" % ("检测到变化，但未写入" if changed else "无变化"))
        print("站点探测：%s" % (
            "跳过" if args.no_probe else
            "正常 %d / 连不上 %d" % (
                sum(1 for v in probes.values() if v[0] == "ok"),
                sum(1 for v in probes.values() if v[0] == "bad"))))
        return 0

    if changed:
        merged["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        merged["updatedBy"] = "github-actions"
        payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        # config.json 与 api.json 内容始终一致：
        # config.json 是电视端在用的地址（新路径，CDN 缓存更可靠），api.json 保留兼容。
        for path in (CONFIG_PATH, API_PATH):
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
        print("已写入 config.json 与 api.json")
        headline = "完成：已合并新内容（站点 +%d，直播 +%d）" % (
            adds["sites_added"], adds["lives_added"])
        detail = "done"
    else:
        print("无变化，不写配置文件")
        headline = "完成：没有新内容"
        detail = "same"

    write_status(started, headline, detail, total, ok_count, merged)
    write_vod_status(merged, probes)
    print("已更新 sync-status.md 与 vod-status.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

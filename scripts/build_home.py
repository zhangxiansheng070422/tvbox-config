# -*- coding: utf-8 -*-
"""
把「宝盒」配置做底座（保留它的一级/二级菜单），再把自己的点播源附加进去，
产出一个可直接给 TVBox 用的单地址配置 dist/home.json。

- 一级/二级菜单由宝盒第一个站点（豆瓣 / csp_Douban）提供，所以它必须留在第一位
- 自建站点都是 type=1 的 CMS 直连，不需要 spider，可以安全追加
- 底座优先读 data/baohuo.json（已入库），没有再退回仓库根目录的 bh.bin
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASES = [
    os.path.join(BASE, "data", "baohuo.json"),
    os.path.join(BASE, "bh.bin"),
]
OURS = os.path.join(BASE, "dist", "tvbox-sites.json")
OUT = os.path.join(BASE, "dist", "home.json")

# 与 sync.py 保持一致：这些类别不要
EXCLUDE_WORDS = [
    "小学", "初中", "高中", "中小学", "幼儿", "早教", "智教", "教育",
    "戏曲", "戏剧", "京剧", "越剧", "音乐", "听歌", "歌曲", "MV",
    "哔哩", "bilibili", "B站", "观影", "短剧",
]


def excluded(site):
    text = " ".join(str(site.get(k, "")) for k in ("name", "key", "api"))
    for w in EXCLUDE_WORDS:
        if w.lower() in text.lower():
            return w
    return None


def load_base():
    for p in BASES:
        if os.path.exists(p) and os.path.getsize(p) > 1024:
            try:
                with open(p, encoding="utf-8") as f:
                    return json.load(f), p
            except Exception as e:
                print("底座 %s 解析失败: %s" % (p, e))
    return None, None


def main():
    base, src = load_base()
    if base is None:
        print("找不到宝盒底座（data/baohuo.json 或 bh.bin），跳过 home.json 生成")
        return 0

    if not os.path.exists(OURS):
        print("找不到 %s，先跑 sync.py" % OURS)
        return 0
    ours = json.load(open(OURS, encoding="utf-8"))

    kept, dropped = [], []
    for s in base.get("sites", []):
        w = excluded(s)
        if w:
            dropped.append(s.get("name"))
        else:
            kept.append(s)

    first = kept[0].get("name") if kept else None
    existing_keys = {s.get("key") for s in kept}
    added = 0
    for s in ours.get("sites", []):
        s = dict(s)
        key = "my_" + str(s.get("key", "x"))
        if key in existing_keys:
            continue
        s["key"] = key
        kept.append(s)
        existing_keys.add(key)
        added += 1

    out = dict(base)
    out["sites"] = kept
    out["name"] = "宝盒菜单 + jingjian 自建源"
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("底座: %s" % os.path.relpath(src, BASE))
    print("宝盒原始站点: %d" % len(base.get("sites", [])))
    print("剔除(教育/戏曲等): %d %s" % (len(dropped), dropped))
    print("保留宝盒: %d，第一个(决定菜单): %s" % (len(kept) - added, first))
    print("追加自建: %d" % added)
    print("合计: %d 站" % len(kept))
    print("输出: %s (%d 字节)" % (OUT, os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

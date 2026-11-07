# -*- coding: utf-8 -*-
"""上传指定的一个或多个文件到 GitHub（避免把 tools/ 之类的大目录一起推上去）

用法：
    python scripts/push_files.py dist/home.json data/baohuo.json "提交说明"
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "zhangxiansheng070422/tvbox-config"
BRANCH = "main"


def token():
    with open(os.path.join(ROOT, ".github_token"), encoding="utf-8") as f:
        return f.read().strip()


def req(method, path, body=None, tok=""):
    url = "https://api.github.com" + path
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + tok)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        print("HTTP %s: %s" % (e.code, e.read().decode()[:300]))
        return None


def push(rel_path, message, tok):
    full = os.path.join(ROOT, rel_path)
    content = open(full, "rb").read()
    b64 = base64.b64encode(content).decode()

    cur = req("GET", "/repos/%s/contents/%s?ref=%s" % (REPO, rel_path, BRANCH), tok=tok)
    sha = cur.get("sha") if isinstance(cur, dict) else None

    body = {"message": message, "content": b64, "branch": BRANCH}
    if sha:
        body["sha"] = sha
    res = req("PUT", "/repos/%s/contents/%s" % (REPO, rel_path), body, tok)
    if res and res.get("content"):
        print("✔ %s (%d 字节)" % (rel_path, len(content)))
        return True
    print("✗ %s" % rel_path)
    return False


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    msg = args[-1]
    files = args[:-1]
    tok = token()
    ok = True
    for f in files:
        ok = push(f, msg, tok) and ok
    sys.exit(0 if ok else 1)

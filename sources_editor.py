#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地点播源编辑器。

双击 `一键更新点播源.bat` 启动，会自动打开一个本地网页：
把地址粘进去（或者把 txt 拖进去），点一下「提交并生效」，
它就用你仓库的 Token 直接把 sources.txt 更新掉，GitHub Actions 随即自动抓取合并。

不需要懂 git，不需要打开 GitHub 网页。
关掉那个黑窗口就等于关掉这个工具。
"""

import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(ROOT, ".github_token")
OWNER = "zhangxiansheng070422"
REPO = "tvbox-config"
BRANCH = "main"
FILE_IN_REPO = "sources.txt"
PORT_START = 8899
CST = timezone(timedelta(hours=8))

# 国内直连 api.github.com 可能被 DNS 劫持（表现为假 401），按顺序试：
# 先直连，失败再走本机代理。
ENDPOINTS = ["", "http://127.0.0.1:7890"]
_direct_ok = [True]

DRY = os.environ.get("TVBOX_EDITOR_DRY") == "1"


def _request(method, url, token, body=None, timeout=25):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "tvbox-editor/1.0")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def gh(method, path, token, body=None):
    """调 GitHub API，直连不行就换代理。"""
    url = "https://api.github.com" + path
    order = list(ENDPOINTS) if _direct_ok[0] else list(reversed(ENDPOINTS))
    last = None
    for proxy in order:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"https": proxy, "http": proxy}) if proxy
            else urllib.request.ProxyHandler({}))
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "tvbox-editor/1.0")
            if data is not None:
                req.add_header("Content-Type", "application/json")
            with opener.open(req, timeout=25) as resp:
                raw = resp.read().decode("utf-8")
            _direct_ok[0] = (proxy == "")
            return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            # 真的收到了 HTTP 响应，说明这条通道是通的，不用换
            detail = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(detail).get("message", detail[:200])
            except Exception:
                msg = detail[:200]
            _direct_ok[0] = (proxy == "")
            raise RuntimeError("GitHub 返回 %s：%s" % (e.code, msg))
        except Exception as e:
            last = e
            continue
    raise RuntimeError("连不上 GitHub（%s）。请确认 Clash / 代理软件是开着的。" % last)


def read_token():
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError("找不到 .github_token，这个文件被删了？")
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if not token:
        raise RuntimeError(".github_token 是空的")
    return token


def push_sources(text):
    """把文本写进仓库的 sources.txt。"""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    body_text = "\n".join(lines) + "\n"

    urls = [ln.strip() for ln in lines
            if ln.strip() and not ln.strip().startswith("#")
            and ln.strip().startswith(("http://", "https://"))]

    if DRY:
        return {"ok": True, "dry": True, "urls": len(urls), "bytes": len(body_text)}

    token = read_token()
    path = "/repos/%s/%s/contents/%s" % (OWNER, REPO, urllib.parse.quote(FILE_IN_REPO))

    sha = None
    try:
        info = gh("GET", path + "?ref=" + BRANCH, token)
        sha = info.get("sha")
    except RuntimeError as e:
        if "404" not in str(e):
            raise

    body = {
        "message": "update: sources.txt（本地点播源编辑器 %s）"
                   % datetime.now(CST).strftime("%Y-%m-%d %H:%M"),
        "content": base64.b64encode(body_text.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        body["sha"] = sha
    res = gh("PUT", path, token, body)
    return {
        "ok": True,
        "urls": len(urls),
        "bytes": len(body_text),
        "commit": (res.get("commit") or {}).get("html_url", ""),
        "repo": "https://github.com/%s/%s" % (OWNER, REPO),
    }


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>点播源 · 粘贴就生效</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 28px 20px 40px;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f2f4f7; color: #1a1d23;
  }
  .wrap { max-width: 880px; margin: 0 auto; }
  h1 { font-size: 21px; margin: 0 0 6px; font-weight: 650; }
  .sub { font-size: 13.5px; color: #6b7280; margin: 0 0 20px; line-height: 1.6; }
  .card {
    background: #fff; border-radius: 12px; padding: 18px;
    box-shadow: 0 1px 3px rgba(16,24,40,.08), 0 1px 2px rgba(16,24,40,.04);
  }
  #drop {
    border: 1.5px dashed #cfd6e0; border-radius: 10px; transition: .15s;
    background: #fafbfc;
  }
  #drop.hot { border-color: #2f6fed; background: #eef4ff; }
  textarea {
    width: 100%; height: 300px; border: 0; outline: 0; resize: vertical;
    padding: 14px; border-radius: 10px; background: transparent;
    font: 13px/1.75 ui-monospace, SFMono-Regular, Consolas, monospace;
    color: #1a1d23;
  }
  textarea::placeholder { color: #9aa3af; }
  .row { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
  button {
    font: inherit; font-size: 14px; border: 0; border-radius: 9px;
    padding: 10px 20px; cursor: pointer; transition: .15s;
  }
  button:disabled { opacity: .55; cursor: default; }
  .primary { background: #2f6fed; color: #fff; font-weight: 600; }
  .primary:hover:not(:disabled) { background: #2558c9; }
  .ghost { background: #eef1f5; color: #3b4250; }
  .ghost:hover { background: #e3e8ef; }
  .tip { font-size: 12.5px; color: #8a919c; margin-left: auto; }
  #status { margin-top: 16px; font-size: 13.5px; line-height: 1.7; display: none; }
  #status.show { display: block; }
  .ok { background: #e9f8ef; border: 1px solid #b7e6c8; color: #14663a; padding: 12px 14px; border-radius: 10px; }
  .err { background: #fdecec; border: 1px solid #f6c2c2; color: #a32020; padding: 12px 14px; border-radius: 10px; }
  .busy { background: #eef4ff; border: 1px solid #c9daff; color: #1d4ed8; padding: 12px 14px; border-radius: 10px; }
  code { background: #eef1f5; padding: 2px 6px; border-radius: 5px; font-size: 12.5px; }
  a { color: #2f6fed; }
  .foot { margin-top: 22px; font-size: 12.5px; color: #8a919c; line-height: 1.9; }
</style>
</head>
<body>
<div class="wrap">
  <h1>点播源 · 粘贴就生效</h1>
  <p class="sub">
    一行一个地址，<code>#</code> 开头不生效。中文域名、多仓接口都能直接粘，脚本会自动处理。<br>
    也可以把 <code>.txt</code> 文件直接拖进下面的框里。
  </p>

  <div class="card">
    <div id="drop">
      <textarea id="box" spellcheck="false" placeholder="http://example.com/tv&#10;https://example.com/config.json&#10;&#10;（一行一个，粘完点下面的按钮）"></textarea>
    </div>
    <div class="row">
      <button class="primary" id="go">提交并生效</button>
      <button class="ghost" id="pick">选一个 txt 文件</button>
      <button class="ghost" id="clear">清空</button>
      <span class="tip" id="count">0 条地址</span>
    </div>
    <div id="status"></div>
  </div>

  <div class="foot">
    提交后 GitHub 会在 1 分钟内自动抓取、去重、合并到 <code>config.json</code>。<br>
    想看结果：<a href="https://github.com/__OWNER__/__REPO__/blob/main/vod-status.md" target="_blank">vod-status.md</a>
    ·
    <a href="https://github.com/__OWNER__/__REPO__/actions" target="_blank">Actions 运行记录</a><br>
    这个页面只在你自己的电脑上跑，Token 不会离开本机。
  </div>
</div>

<input type="file" id="file" accept=".txt,text/plain" style="display:none">

<script>
const box = document.getElementById('box');
const drop = document.getElementById('drop');
const statusEl = document.getElementById('status');
const countEl = document.getElementById('count');
const go = document.getElementById('go');

function countUrls() {
  const n = box.value.split(/\r?\n/).filter(l => {
    const s = l.trim();
    return s && !s.startsWith('#') && /^https?:\/\//i.test(s);
  }).length;
  countEl.textContent = n + ' 条地址';
  go.disabled = n === 0;
}
box.addEventListener('input', countUrls);

['dragenter', 'dragover'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.add('hot');
}));
['dragleave', 'drop'].forEach(e => drop.addEventListener(e, ev => {
  ev.preventDefault(); drop.classList.remove('hot');
}));
drop.addEventListener('drop', ev => {
  const f = ev.dataTransfer.files[0];
  if (f) readFile(f);
});
document.getElementById('pick').onclick = () => document.getElementById('file').click();
document.getElementById('file').onchange = ev => {
  const f = ev.target.files[0];
  if (f) readFile(f);
};
function readFile(f) {
  const r = new FileReader();
  r.onload = () => { box.value = r.result; countUrls(); };
  r.readAsText(f, 'utf-8');
}
document.getElementById('clear').onclick = () => { box.value = ''; countUrls(); statusEl.className = ''; };

function say(kind, html) {
  statusEl.className = 'show ' + kind;
  statusEl.innerHTML = html;
}

go.onclick = async () => {
  go.disabled = true;
  say('busy', '正在提交到 GitHub ...');
  try {
    const resp = await fetch('/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({content: box.value})
    });
    const d = await resp.json();
    if (!d.ok) throw new Error(d.error || '提交失败');
    say('ok',
      '已提交 <b>' + d.urls + '</b> 条地址（' + d.bytes + ' 字节）。<br>' +
      'GitHub 正在自动抓取，大约 1 分钟后去看 ' +
      '<a href="https://github.com/__OWNER__/__REPO__/blob/main/vod-status.md" target="_blank">vod-status.md</a> ' +
      '就知道每个站通不通。' +
      (d.commit ? '<br><a href="' + d.commit + '" target="_blank">查看这次提交</a>' : ''));
  } catch (e) {
    say('err', '没成功：' + e.message);
  }
  go.disabled = false;
  countUrls();
};

countUrls();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = PAGE.replace("__OWNER__", OWNER).replace("__REPO__", REPO)
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/ping":
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"ok": False, "error": "not found"}))

    def do_POST(self):
        if self.path != "/submit":
            self._send(404, json.dumps({"ok": False, "error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            content = payload.get("content") or ""
            if not content.strip():
                raise ValueError("内容是空的")
            self._send(200, json.dumps(push_sources(content), ensure_ascii=False))
        except Exception as e:
            self._send(200, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


def pick_port():
    for port in range(PORT_START, PORT_START + 12):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("8899-8910 端口都被占用了，关掉别的程序再试")


def main():
    port = pick_port()
    url = "http://127.0.0.1:%d/" % port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("=" * 58)
    print("  点播源编辑器已启动")
    print("  浏览器地址：%s" % url)
    print("  粘贴内容 → 点「提交并生效」→ 关闭这个窗口即可退出")
    print("=" * 58)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

#!/data/data/com.termux/files/usr/bin/bash
# 手机端：拉成品 → 解压 → 启动 LunaTV（可重复执行）
PC1="http://10.102.10.203:8080/luna-linux.tar.gz"
PC2="http://192.168.3.8:8080/luna-linux.tar.gz"
REMOTE="https://gh-proxy.com/https://github.com/zhangxiansheng070422/lunatv-build/releases/download/latest/lunatv-standalone.tar.gz"
APP="$HOME/lunatv"
TGZ="$HOME/luna.tgz"
LOG="$HOME/luna.log"
NEED=25000000

termux-wake-lock 2>/dev/null

get() {
  rm -f "$TGZ"
  for U in "$PC1" "$PC2" "$REMOTE"; do
    echo "-- 尝试 $U"
    curl -L --max-time 900 -o "$TGZ" "$U" 2>/dev/null
    SZ=$(stat -c %s "$TGZ" 2>/dev/null || echo 0)
    echo "   得到 $((SZ/1048576)) MB"
    if [ "$SZ" -gt $NEED ] && tar -tzf "$TGZ" >/dev/null 2>&1; then
      echo "   校验通过"
      return 0
    fi
  done
  return 1
}

if [ ! -f "$APP/server.js" ]; then
  echo "==== 下载成品 ===="
  if ! get; then echo "!! 三个下载源都失败"; exit 1; fi
  echo "==== 解压 ===="
  rm -rf "$APP"; mkdir -p "$APP"
  tar -xzf "$TGZ" -C "$APP"
  echo "文件数: $(find "$APP" -type f | wc -l)"
fi

echo "==== 启动 ===="
pkill -f "node server.js" 2>/dev/null
sleep 1
cd "$APP" || exit 1
export USERNAME=admin
export PASSWORD=123456
export NEXT_PUBLIC_SITE_NAME="家庭影院"
export PORT=3000
export HOSTNAME=0.0.0.0
export NODE_ENV=production
nohup node server.js > "$LOG" 2>&1 &
sleep 9

CODE=$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://127.0.0.1:3000 2>/dev/null)
IP=$(ip -4 a 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)
[ -z "$IP" ] && IP=$(ifconfig 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)

# 让以后打开 Termux 就自动拉起服务
grep -q "lunatv-autostart" "$HOME/.bashrc" 2>/dev/null || {
  printf '\n# lunatv-autostart\nif [ -f %s/server.js ]; then (cd %s && USERNAME=admin PASSWORD=123456 PORT=3000 HOSTNAME=0.0.0.0 nohup node server.js > %s 2>&1 &) ; fi\n' "$APP" "$APP" "$LOG" >> "$HOME/.bashrc"
}
mkdir -p "$HOME/.termux/boot" 2>/dev/null
printf '#!/data/data/com.termux/files/usr/bin/sh\ntermux-wake-lock\ncd %s && USERNAME=admin PASSWORD=123456 PORT=3000 HOSTNAME=0.0.0.0 node server.js > %s 2>&1\n' "$APP" "$LOG" > "$HOME/.termux/boot/start-luna.sh"
chmod +x "$HOME/.termux/boot/start-luna.sh" 2>/dev/null

echo ""
if [ "$CODE" = "200" ] || [ "$CODE" = "307" ] || [ "$CODE" = "302" ]; then
  echo "=========================================="
  echo "  LunaTV 已启动"
  echo "  电视/电脑访问: http://$IP:3000"
  echo "  用户名 admin   密码 123456"
  echo "=========================================="
else
  echo "!! 启动异常 code=$CODE，日志："
  tail -15 "$LOG"
fi

#!/data/data/com.termux/files/usr/bin/bash
# LunaTV(MoonTV) 在安卓手机 Termux 里的一键部署脚本
# 用法：bash moontv-install.sh
set -e

PORT=${PORT:-3000}
PASSWORD=${PASSWORD:-moontv123}
SRC="/data/data/com.termux/files/home/LunaTV"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

say "1/6 更新软件源"
pkg update -y >/dev/null 2>&1 || pkg update -y

say "2/6 安装 Node 与构建工具（第一次会比较久）"
pkg install -y nodejs-lts git python make clang >/dev/null 2>&1 || \
  pkg install -y nodejs git python make clang

say "Node 版本：$(node -v)"

say "3/6 安装 pnpm"
npm i -g pnpm@latest >/dev/null 2>&1
echo "pnpm $(pnpm -v)"

say "4/6 下载源码（走镜像，比 git clone 快）"
if [ ! -d "$SRC" ]; then
  cd /data/data/com.termux/files/home
  rm -f lunatv.tar.gz
  curl -L --max-time 600 -o lunatv.tar.gz \
    "https://gh-proxy.com/https://github.com/MoonTechLab/LunaTV/archive/refs/heads/main.tar.gz"
  tar xzf lunatv.tar.gz
  mv LunaTV-main "$SRC" 2>/dev/null || true
  rm -f lunatv.tar.gz
fi
cd "$SRC"

say "5/6 安装依赖并构建（手机上大约 10-30 分钟，别锁屏）"
pnpm install
pnpm build

say "6/6 启动服务"
termux-wake-lock 2>/dev/null || echo "（拿不到唤醒锁，请手动在设置里允许 Termux 后台运行）"

IP=$(ip route get 1 2>/dev/null | awk '{print $NF; exit}')
[ -z "$IP" ] && IP=$(ifconfig wlan0 2>/dev/null | awk '/inet /{print $2}' | head -1)

cat <<EOF

========================================
 LunaTV 已启动
   本机访问： http://127.0.0.1:$PORT
   电视/电脑： http://$IP:$PORT
   访问密码： $PASSWORD
========================================
按 Ctrl+C 停止。下次开机后重新启动：
  cd ~/LunaTV && node start.js
EOF

PASSWORD="$PASSWORD" PORT="$PORT" node start.js

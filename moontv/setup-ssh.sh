#!/data/data/com.termux/files/usr/bin/bash
# 在 Termux 里开 SSH 服务，供电脑免密接管
# 用法：bash setup-ssh.sh
set -u

MIRRORS="https://gh-proxy.com/https://raw.githubusercontent.com/zhangxiansheng070422/tvbox-config/main/moontv/authorized_keys.txt
https://ghfast.top/https://raw.githubusercontent.com/zhangxiansheng070422/tvbox-config/main/moontv/authorized_keys.txt
https://raw.githubusercontent.com/zhangxiansheng070422/tvbox-config/main/moontv/authorized_keys.txt"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

say "1/4 安装 openssh"
pkg install -y openssh >/dev/null 2>&1 || pkg install -y openssh

say "2/4 写入公钥"
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
: > "$HOME/.ssh/authorized_keys"
OK=0
for u in $MIRRORS; do
  if curl -fsSL --max-time 25 "$u" -o "$HOME/.ssh/authorized_keys" 2>/dev/null; then
    if grep -q "ssh-ed25519" "$HOME/.ssh/authorized_keys" 2>/dev/null; then OK=1; break; fi
  fi
done
if [ "$OK" -ne 1 ]; then
  echo "公钥下载失败，请确认网络后重试"
  exit 1
fi
chmod 600 "$HOME/.ssh/authorized_keys"
echo "公钥已写入（$(wc -c < "$HOME/.ssh/authorized_keys") 字节）"

say "3/4 启动 sshd"
ssh-keygen -A >/dev/null 2>&1 || true
pkill sshd >/dev/null 2>&1 || true
sleep 1
sshd 2>/dev/null || $(command -v sshd) 2>/dev/null || true
sleep 2

if ! pgrep -f sshd >/dev/null 2>&1; then
  echo "sshd 启动失败"
  exit 1
fi

say "4/4 完成"
IP=$(ip -4 a 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)
[ -z "$IP" ] && IP=$(ifconfig 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)
echo "USER=$(whoami)"
echo "IP=$IP"
echo "PORT=8022"
echo "--------------------------------------"
echo "把上面三行发给电脑端即可"
echo "--------------------------------------"

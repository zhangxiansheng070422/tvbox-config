#!/data/data/com.termux/files/usr/bin/bash
# 局域网版：在 Termux 里开 SSH 服务供电脑接管（零外网依赖）
set -u

PUB="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINkNMW+l/NrLM5VFg3t505yEIvhJVXC6ttUzRi8jpr25 workbuddy-phone"

say() { printf "\n\033[1;36m==> %s\033[0m\n" "$1"; }

say "1/4 安装 openssh（走 Termux 源）"
if ! command -v sshd >/dev/null 2>&1; then
  pkg install -y openssh || { echo "安装失败，请检查网络（Termux 源）"; exit 1; }
fi

say "2/4 写入公钥"
mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
printf '%s\n' "$PUB" > "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
echo "公钥 $(wc -c < "$HOME/.ssh/authorized_keys") 字节"

say "3/4 启动 sshd"
ssh-keygen -A >/dev/null 2>&1 || true
pkill sshd >/dev/null 2>&1 || true
sleep 1
sshd
sleep 2
pgrep -f sshd >/dev/null 2>&1 || { echo "sshd 没起来"; exit 1; }

say "4/4 完成"
IP=$(ip -4 a 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)
[ -z "$IP" ] && IP=$(ifconfig 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | head -1)
echo "USER=$(whoami)"
echo "IP=$IP"
echo "PORT=8022"
echo "----------------------------------------"
echo " 把 USER 那行发给电脑即可"
echo "----------------------------------------"

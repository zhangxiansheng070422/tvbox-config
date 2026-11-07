# TVBox 配置 · GitHub 托管版

把 `api.json` 放在 GitHub 上，由 GitHub Actions 定时更新，电视端填一个 CDN 链接。
**电脑关机也能用，异地也能看**，不需要 Tailscale，也不需要端口转发。


## 零、在家能用什么、不能用什么（先看这段）

这份仓库只托管**配置**（约 500 字节），不托管视频。所以：

| 内容 | 在家能否用 | 原因 |
| --- | --- | --- |
| 配置本身 | ✅ 能 | 就在这个仓库里 |
| `sub/live.txt` 里的直播源 | ✅ 能 | 只要地址是公网可访问的 |
| 办公室电脑上的本地片库 | ❌ 不能 | 地址是办公室内网 `192.168.x`，家里访问不到 |

所以这份 `api.json` 里**故意没有**「本地片库」这个站点——放进去只会在电视上出现一个点不开的空分类。

要让家里的电视看到办公室电脑上那几十 GB 视频，需要一条**从家连回办公室的通道**（Tailscale / frp / 公网端口映射），那不是仓库能解决的事。

## 一、部署（双击一下，全自动）

> **实测结论：`github.com` 网页在部分办公网络下无法访问（TCP 443 被阻断），
> 但 `api.github.com` 及镜像通道可用。** 所以注册、拿 Token 这两步请用手机流量
> 或家里的网络完成；拿到 Token 后，本机运行部署脚本即可全自动完成，脚本会在直连
> 失败时自动切换到 `gh-proxy.com` 镜像。

**前提：你得先有一个 GitHub 账号。** 注册要邮箱收验证码，GitHub 明确禁止他人代注册，
这一步谁都替不了你，大约 3 分钟：

1. 打开 https://github.com/signup
2. 填邮箱、密码、用户名（用户名只能用英文和数字，比如 `zhangwei2026`）
3. 收邮件点验证链接 → 完成

有账号之后，**只剩两个动作**：

**动作 1 · 拿一串钥匙（Token）**

1. 打开 https://github.com/settings/tokens/new
2. `Note` 随便填，比如 `tvbox`
3. `Expiration` 选 `90 days`
4. 下面勾 **`repo`** 和 **`workflow`** 这两个（workflow 藏得深，要往下找）
5. 拉到最底 → **Generate token** → 复制那一长串 `ghp_...`
   （这串只显示一次，先粘到记事本里）

**动作 2 · 双击 `双击这里部署.bat`**

会弹出一个黑窗口，把 Token 粘进去按回车，问仓库名直接按回车。

几十秒后窗口会打印一行地址，形如：

```
https://cdn.jsdelivr.net/gh/你的用户名/tvbox-config@main/api.json
```

**这行就是电视端要填的东西**，同时会存到隔壁的 `电视端填这个地址.txt` 里。

脚本自动完成：建仓库 → 上传全部文件 → 打开任务写权限 → 触发一次任务验证 → 生成地址。

> 同一份脚本可以重复运行，改动会覆盖上去，不会重复建仓库。

## 和本机那套的分工

| | 本机 Docker 版（`../tvbox/`） | 本仓库 |
| --- | --- | --- |
| 配置存放 | 本机磁盘 | GitHub 仓库 |
| 定时更新 | 本机容器，电脑要开着 | GitHub Actions，电脑不用开 |
| 电视端地址 | `http://192.168.18.20:8080/api.json` | `https://cdn.jsdelivr.net/gh/用户名/仓库名@main/api.json` |
| 适用场景 | 家里同一网络 | 出门在外、多地点 |

两套可以同时用，改一边不会影响另一边。

## 文件

```
.
├─ api.json                     # TVBox 主配置（Actions 会改这个文件并提交）
├─ sources.txt                  # 订阅地址清单，一行一个
├─ sub/live.txt                 # 直播源
├─ scripts/sync.py              # 合并脚本，Actions 调它
└─ .github/workflows/sync.yml   # 定时任务：每 6 小时跑一次
```

## 一、推到 GitHub

```bash
cd tvbox-github
git init
git add .
git commit -m "init: tvbox config"
git branch -M main
git remote add origin https://github.com/你的用户名/tvbox-config.git
git push -u origin main
```

> 仓库**必须是 public**。私有仓库的 raw 链接要带 token，TVBox 客户端不支持带认证头，
> 拉不到。所以这个仓库里**不要放任何密码、token、内网地址**。

## 二、确认 Actions 有写权限

仓库 → Settings → Actions → General → Workflow permissions →
选 **Read and write permissions** → Save。

不开这一项，定时任务能跑但推送会被拒。

## 三、电视端填哪个地址

三选一，按国内连通性排序：

| 方式 | 地址格式 | 说明 |
| --- | --- | --- |
| **jsDelivr（推荐）** | `https://cdn.jsdelivr.net/gh/用户名/仓库名@main/api.json` | 国内速度稳定，有缓存 |
| Statically | `https://cdn.statically.io/gh/用户名/仓库名/main/api.json` | 备用 CDN |
| GitHub Raw | `https://raw.githubusercontent.com/用户名/仓库名/main/api.json` | 国内常被墙，不推荐 |

**jsDelivr 会缓存约 12 小时**，刚改完看不到变化是正常的。要立刻刷新：

```
https://purge.jsdelivr.net/gh/用户名/仓库名@main/api.json
```

浏览器打开这个地址就完成清除，然后再拉配置。

## 四、改源

两种都行：

1. **网页改**：GitHub 网页打开 `sources.txt` → 编辑 → Commit。下次 Actions 跑就生效。
2. **手动触发**：仓库 → Actions → `sync-sources` → Run workflow。

也可以本地改完 `git push`，效果相同。

## 五、合并规则

和本机版一致：

- **只增不删**：已在你 `api.json` 里的条目不会被删，新条目按 `key` / `name` / `api` 去重后追加。
- **本地优先**：`spider` 手工设过就不被远端替换。
- 全篇有变化才提交，没变化不产生空提交。
- 单条源失败只记日志，不影响其他源；全部失败时 `api.json` 一律不动。
- 每次提交都在 git 历史里，回滚就是 `git revert`。

## 六、注意

- 公开仓库 = 所有人可见，包括你填的订阅地址。介意的话用本机那套。
- Actions 免费额度对公开仓库不限时长，这个任务每次只跑几秒。
- `scripts/sync.py` 也可以本地跑：`python scripts/sync.py --dry-run` 先看结果不写文件。

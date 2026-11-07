# TVBox 配置 · GitHub 托管版

配置放在 GitHub 上，由 GitHub Actions 每 6 小时自动抓取、合并、提交，电视端填一个链接。
**电脑关机也能用**，不需要 Tailscale，也不需要端口转发。

## 现在它在自动做什么

| 项目 | 谁在更新 | 多久一次 | 状态页 |
| --- | --- | --- | --- |
| 直播源 `sub/live.txt` | 从 3 个公开 IPTV 列表抓取 + 并入手工种子 | 6 小时 | `live-status.md` |
| 点播站点 `config.json` 的 `sites` | 抓 `sources.txt` 里的地址，去重合并 | 6 小时 / 你改了就立刻跑 | `sync-status.md` |
| 站点活没活着 | 逐个探测接口，标正常 / 待观察 / 连不上 | 6 小时 | `vod-status.md` |

**唯一需要你动手的地方**：`sources.txt` 里填点播配置地址。填一次，之后全自动。

## 点播源：怎么做到「抓取 → 调用 → 更新 → 自动配置」

整条链是自动的，只有第一环需要你给一个地址：

```
你在 sources.txt 加一行地址
        ↓  提交（网页上点一下，或者什么都不做等 6 小时）
GitHub Actions 自动触发
        ↓
scripts/sync.py 抓取 → 校验是不是合法配置 → 按 key/api/name 去重
        ↓
写回 config.json + api.json，探测每个站点接口
        ↓
自动 commit + push 回仓库
        ↓
电视端重新加载配置 = 看到新站点
```

支持的地址有两种写法，混着写也行：

1. **直接的配置地址** —— 返回 JSON，里面有 `sites` / `lives` / `parses` / `spider`
2. **地址清单** —— 一个纯文本，里面一行一个配置地址；脚本会自动展开一层
   （清单套清单最多两层，一个清单最多展开 20 条，防止被喂几千条把机器跑满）

### 你只要做这三步（在网页上，不用装任何东西）

1. 打开仓库 → 点 `sources.txt` → 右上角铅笔图标
2. 在末尾加一行，比如 `https://你的地址/config.json`（把 `#` 去掉才生效）
3. 拉到下面点 `Commit changes`

提交后 Actions 会自动跑（因为 workflow 监听了 `sources.txt` 的改动），
不用等 6 小时。跑完电视端重新加载一次配置就行。

### 手工补站点：`sites/` 目录

不想走网络、或者只有一两个站点，直接在这个目录丢一个 `.json` 文件：

```json
{ "sites": [ { "key": "my1", "name": "我的片库", "type": 1, "api": "https://example.com/api.php/provide/vod/" } ] }
```

也会被自动合并进去。详见 `sites/README.md`。

### 安全阀

- **只增不删**：已有站点不会被远端删掉。
- **不覆盖直播**：抓点播不会打乱你手工调好的 110 个台（要覆盖得显式加 `--allow-lives`）。
- **不采纳远端 spider**：spider 是会下载执行的 jar，来源不明的不自动加载。
- **全挂不动手**：所有地址都抓不到时，配置文件保持原样，只写一条失败记录。
- **单条失败不影响其他**：一条地址挂了，剩下的照抓。

## 部署（已经部署过可以跳过）

双击 `双击这里部署.bat`，粘 Token，问仓库名直接回车。几十秒后打印电视端地址。

脚本会自动：建仓库 → 上传文件 → 打开 Actions 写权限 → 触发一次任务 → 生成地址文件。

### 电视端填哪个地址

| 方式 | 地址 | 说明 |
| --- | --- | --- |
| **jsDelivr（推荐）** | `https://cdn.jsdelivr.net/gh/用户名/仓库名@main/config.json` | 国内稳定，有缓存 |
| Statically | `https://cdn.statically.io/gh/用户名/仓库名/main/config.json` | 备用 CDN |
| GitHub Raw | `https://raw.githubusercontent.com/用户名/仓库名/main/config.json` | 实时、无缓存，但国内常被墙 |

jsDelivr 有缓存，刚改完看不到变化是正常的。要立刻刷新，浏览器打开：

```
https://purge.jsdelivr.net/gh/用户名/仓库名@main/config.json
```

## 文件

```
.
├─ config.json                  # 电视端在用的主配置（Actions 会改这个并提交）
├─ api.json                     # 旧路径，内容与 config.json 永远一致（兼容用）
├─ sources.txt                  # ★ 点播订阅地址清单（你填，机器抓）
├─ sites/                       # 手工站点片段，丢 *.json 进来就会被合并
├─ sub/live.txt                 # 直播源（自动生成，别手改）
├─ sub/live_seed.txt            # 精选种子：逐台实测过的线路，永远排最前
├─ sync-status.md               # 点播同步运行记录（自动生成）
├─ vod-status.md                # 每个站点活没活着（自动生成）
├─ live-status.md               # 直播抓取运行记录（自动生成）
├─ scripts/sync.py              # 点播：抓取 + 合并 + 探测 + 写状态页
├─ scripts/sync_live.py         # 直播：抓取 + 合并 + 写状态页
└─ .github/workflows/sync.yml   # 定时任务：每 6 小时 + 你一改 sources 就触发
```

## 直播源是怎么来的

`sub/live.txt` 一个文件对外，内容是两段拼起来的：

1. **种子段**（`sub/live_seed.txt`）—— 逐台实测过、确实能播的线路，永远排最前。
2. **抓取段** —— 每 6 小时从三个公开 IPTV 列表拉最新频道，清洗、去重、按频道归并。

合并规则：

- `CCTV-1` / `CCTV1` / `CCTV-1综合` 视为一台，多条线路最多留 4 条，种子线路排前面。
- **只排序、不删源**。GitHub 的机器在境外，对国内直播源判断不准，误杀比留死链更糟。
- **源不齐时只增不减**；可用频道少于 20 个判定异常，保留上一版不动。

想固定加台？改 `sub/live_seed.txt`，一行 `频道名,线路1,线路2`。

## 怎么确认它在工作

打开仓库，看这三个文件的第一屏：

- `sync-status.md` —— 点播同步跑没跑、抓到几个站
- `vod-status.md` —— 每个站点现在通不通
- `live-status.md` —— 直播抓了多少台

想看详细输出，去 `Actions` 页面，绿勾成功、红叉失败。

`sources.txt` 为空时 `sync-status.md` 会一直显示「跳过」——**任务在跑，只是没有地址可抓**。

## 本地跑

```bash
python scripts/sync.py --dry-run    # 只看会发生什么，不写文件
python scripts/sync.py --no-probe   # 跳过站点探测，快
```

## 注意

- 公开仓库 = 所有人可见，**包括你填的订阅地址**。介意的话别放私密接口。
- Actions 对公开仓库不限时长，这个任务每次只跑十几秒。
- 仓库里有 `.github_token` 的话，`.gitignore` 已经把它挡住了，不会被上传。

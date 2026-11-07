# 点播站点状态

> 由 GitHub 定时任务自动维护，每 6 小时更新一次。
> 「正常」= 接口连得上；「待观察」= 接口回了 403/404（多半要求带参数，一般还活着）；
> 「连不上」= 域名或网络不通，这个站点在电视端多半点不开。

## 概况

- **检查时间**：2026-11-07 19:41（北京时间）
- **点播站点**：28 个（正常 21 / 待观察 1 / 连不上 6 / 未探测 0）

## 明细

| 站点 | 类型 | 状态 | 说明 | 接口域名 |
| --- | --- | --- | --- | --- |
| 🎬-爱奇艺- | 1 | 正常 | HTTP 200 | iqiyizyapi.com |
| 🎬豆瓣资源 | 1 | 连不上 | 连不上 | caiji.dbzy5.com |
| 🎬茅台资源 | 1 | 连不上 | 连不上 | caiji.maotaizy.cc |
| 🎬卧龙资源 | 1 | 正常 | HTTP 200 | wolongzyw.com |
| 🎬iKun资源 | 1 | 正常 | HTTP 200 | ikunzyapi.com |
| 🎬电影天堂 | 1 | 正常 | HTTP 200 | caiji.dyttzyapi.com |
| 🎬猫眼资源 | 1 | 正常 | HTTP 200 | api.maoyanapi.top |
| 🎬量子资源 | 1 | 正常 | HTTP 200 | cj.lzcaiji.com |
| 🎬360 资源 | 1 | 正常 | HTTP 200 | 360zyzz.com |
| 🎬极速资源 | 1 | 正常 | HTTP 200 | jszyapi.com |
| 🎬魔都资源 | 1 | 正常 | HTTP 200 | www.mdzyapi.com |
| 🎬非凡资源 | 1 | 正常 | HTTP 200 | api.ffzyapi.com |
| 🎬暴风资源 | 1 | 正常 | HTTP 200 | bfzyapi.com |
| 🎬最大资源 | 1 | 正常 | HTTP 200 | api.zuidapi.com |
| 🎬无尽资源 | 1 | 正常 | HTTP 200 | api.wujinapi.me |
| 🎬新浪资源 | 1 | 正常 | HTTP 200 | api.xinlangapi.com |
| 🎬旺旺资源 | 1 | 正常 | HTTP 200 | api.wwzy.tv |
| 🎬速播资源 | 1 | 正常 | HTTP 200 | subocaiji.com |
| 🎬金鹰点播 | 1 | 正常 | HTTP 200 | jinyingzy.com |
| 🎬飘零资源 | 1 | 待观察 | HTTP 403 | p2100.net |
| 🎬U酷影视 | 1 | 正常 | HTTP 200 | api.ukuapi88.com |
| 🎬光速资源 | 1 | 正常 | HTTP 200 | api.guangsuapi.com |
| 🎬红牛资源 | 1 | 正常 | HTTP 200 | www.hongniuzy2.com |
| 🎬魔都动漫 | 1 | 正常 | HTTP 200 | caiji.moduapi.cc |
| 🎬如意资源 | 1 | 连不上 | 连不上 | pz.168188.dpdns.org |
| 🎬豪华资源 | 1 | 连不上 | 连不上 | pz.168188.dpdns.org |
| 🎬百度云zy | 1 | 连不上 | 连不上 | pz.168188.dpdns.org |
| 🎬艾旦影视 | 1 | 连不上 | 连不上 | pz.168188.dpdns.org |

## 怎么让它自动更新

站点来自 `sources.txt` 里的地址（外加 `sites/` 目录下的本地片段）。
在 `sources.txt` 里加一行、提交，剩下的抓取/合并/去重/提交都是自动的。
地址失效只会让对应站点变成「连不上」，不会把整个配置改坏。

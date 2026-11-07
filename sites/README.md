# 本地站点片段

这个目录是「手工补站点」的入口，不需要动任何脚本。

## 用法

在这里新建一个 `.json` 文件，比如 `my-sites.json`，内容二选一：

```json
{
  "sites": [
    { "key": "my1", "name": "我的片库", "type": 1, "api": "https://example.com/api.php/provide/vod/", "searchable": 1, "quickSearch": 1, "filterable": 1 }
  ]
}
```

或者直接给一个数组：

```json
[
  { "key": "my1", "name": "我的片库", "type": 1, "api": "https://example.com/api.php/provide/vod/" }
]
```

提交后，下一次定时任务会把它并进 `config.json`（已经有同名/同接口的会跳过，不会重复）。

## 注意

- 这个目录里的文件会被合并进**公开仓库**的 `config.json`，接口地址任何人都能看到。私密地址别放这里。
- 只放 `.json`。别的文件（比如这份说明）会被忽略。
- 合并规则是「只增不删」：从这里删掉某个站点，不会自动把它从 `config.json` 里去掉。

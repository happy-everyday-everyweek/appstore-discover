# Only Discover · 推荐页内容仓库

推荐页（App Store Today 风格全宽大卡流）的内容源。仅由维护者一人维护，不开放 Fork/PR 收录。

## 目录结构

```
cards/     每卡一个 JSON 文件，文件名 NN-slug.json（NN 为两位序号 = 展示顺序）
articles/  文章正文 Markdown：articles/<slug>.md
covers/    封面大图：covers/<slug>.png（建议 16:9、≤512KB）
scripts/   发布脚本（CI 调用）
```

## 卡片字段

```json
{
  "type": "collection | article",
  "slug": "本卡唯一标识",
  "label": "左上分类标签（如 编辑精选 / 开源精选 / 文章）",
  "title": "底部大标题",
  "subtitle": "副标题（应用数 / 作者等）",
  "background": {
    "gradient": ["#3A5A8C", "#141C2E"]
  },
  "publish_date": "可选，日期文案"
}
```

background 三种形态（灵活多样，缺省时客户端用默认深色渐变兜底）：

- `{"color": "#8C5A2A"}` 纯色
- `{"gradient": ["#3A5A8C", "#141C2E"]}` 渐变（数组可扩展更多色值）
- `{"cover": "slug.png"}` 封面大图（文件放 covers/）

collection 卡额外字段：`"apps": [1001, 1002]`（应用系统 ID 数组，引用承载仓库 appstore-index 的 app-info.json id）。
article 卡额外字段：`"article": "slug.md"`（文件放 articles/）。

## 发布

维护者改动内容（增删卡片 / 改文案 / 换封面）提交后，CI 立即生成并发布三件套 Release：
full.zip（index.json + assets/）、incremental.zip（结构化差异）、patch.json（解析清单）。
客户端与应用列表聚合包采用同一套增量同步机制（SyncEngine 双通道）。
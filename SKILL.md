---
name: amazon-serp-ads
description: 亚马逊前台 SERP 抓取 + 广告位分析。给一个关键词，连抓多轮（模拟刷新3次），统计哪些 ASIN 是稳定广告位、哪些是自然结果，同时拿到真实美元价格、排名、标题。当老板说「看广告位」「这个关键词谁在投广告」「SERP 分析」「前台搜索排名」「竞品广告位」时触发。
---

# 亚马逊 SERP + 广告位抓取

> **核心：不依赖 linkfox。裸 HTTP 抓 HTML 就能拿广告位，比浏览器更稳。**

---

## 何时用

| 场景 | 示例 |
|---|---|
| ✅ **用** | "看看 dog bed 这个词谁在投广告"、"这个词广告位占了多少"、"我们的排名在哪" |
| ✅ **用** | 选品时看竞争强度（广告位多 = 竞争激烈）|
| ✅ **用** | 盯竞品有没有加投广告 |
| ❌ **不用** | 要月销量/BSR（用 sellersprite）、要看 A+/视频（用 sellersprite）|

---

## 🔴 三个必须知道的坑（实测踩过）

### ① linkfox 的 `amazon/search` 抓不到广告位
```
字段 sponsored 存在，但 48 个结果全是 false
```
**不要指望它**。它只给自然化的结果。

### ② 不加 Cookie → 价格是人民币
```
不加：a-offscreen">CNY 266.63      ← 按中国 IP 返回
加了：a-offscreen">$39.98           ← 正确美元
```
**必须带**：
```python
"Cookie": "i18n-prefs=USD; lc-main=en_US"
```
**不加这个，整个价格对比都是废的。**

### ③ 广告位波动极大 → 单轮不可靠
实测 `dog bed` 连抓 3 轮：

| 轮次 | 结果数 | 广告数 |
|---|---|---|
| 1 | 48 | **0** |
| 2 | 60 | **14** |
| 3 | 48 | **0** |

**老板说「刷新 3 次综合看」完全正确**。单轮可能看到 0 个广告，误判为"没人投广告"。

---

## 执行流程

```bash
# 标准：3 轮（老板方法）
python amz_serp_ads.py --keyword "dog bed" --rounds 3 --gap 6

# 输出 JSON
python amz_serp_ads.py --keyword "dog bed" --rounds 3 --out result.json

# 换邮编（默认 10001 纽约）
python amz_serp_ads.py --keyword "dog bed" --zip 90001
```

### 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--keyword` | 必填 | 搜索词（英文）|
| `--zip` | `10001` | 邮编（10001 纽约最标准）|
| `--rounds` | `1` | **建议 3**（模拟刷新）|
| `--gap` | `3.0` | 每轮间隔秒（**建议 ≥5**，防限流）|
| `--page` | `1` | 页码 |
| `--out` | — | JSON 输出路径 |

### 输出

```
第 1 轮: 60 个结果，其中广告 14 个
第 2 轮: 60 个结果，其中广告 14 个
第 3 轮: 48 个结果，其中广告 0 个

排名    ASIN          广告      价格       标题
1     B0FHKRG6SN    ✅广告     $28.49   Washable Dog Bed for Small Medium Dogs...

【多轮综合分析】
ASIN          广告次数   广告率   结论         标题
B0BDLD2HJZ    2/3      67%    稳定广告位    EHEYCIGA Orthopedic Dog Beds...
```

---

## 广告位判定口径

| 广告率 | 结论 | 含义 |
|---|---|---|
| **≥67%**（≥2/3 轮）| **稳定广告位** | 长期投、预算足，是主要竞争对手 |
| 1/3 ～ 2/3 | 偶发广告位 | 试探性投放 / 分时段 |
| 0 | 自然结果 | 没投广告 |

**关注点**：
- **稳定广告位** = 真正在抢量的对手，值得研究它的价格和内容
- **偶发广告位** = 可能是自动化投放，威胁较小
- **自然位第 1 名但有广告** = 双管齐下，最难打

---

## 技术实现要点

### 广告位 HTML 标记（实测有效）

```html
<span class="sponsored-brand-label-info-desktop">
  <span class="puis-sponsored-label-text">
    <span class="a-size-mini a-color-secondary">Sponsored</span>
  </span>
</span>
```

**检测标记**：
```python
AD_MARKERS = [
    "puis-sponsored-label-text",
    "sponsored-brand-label-info-desktop",
    'aria-label="Sponsored',
]
```

**⚠️ 不要找 `sp-sponsored-result`**（出现 0 次，已废弃）

### 价格提取
```python
re.search(r'a-offscreen">\$([\d,]+\.\d{2})</span>', card)
```

### 商品卡片切分
```python
re.split(r'(?=<div[^>]+data-component-type="s-search-result")', html)
```

### 限流处理
- 空页（<50KB）或出现 "Sorry! Something went wrong" → 重试
- 重试间隔 4/7 秒递增
- **每轮之间间隔 ≥5 秒**

---

## 和浏览器方案对比（实测）

| | curl 裸 HTTP | Playwright headless |
|---|---|---|
| Amazon 拦截 | ✅ **能过** | ❌ **"Sorry! Something went wrong"** |
| 速度 | 快（2秒）| 慢（10秒+）|
| 依赖 | 无 | 需要浏览器 |
| 广告位 | ✅ 能抓 | ❌ 直接被拦 |

**结论**：**抓数据用 curl，不要用浏览器。** Amazon 对 headless 检测很严。

**本地可用的浏览器控制 skill**（需要交互/登录时用）：
- `browser-use`：通用浏览器自动化
- `playwright-browser-automation`：直 Playwright API（Node 版）
- `web-access`：联网操作总入口
- `browser-skill`：腾讯 bsk（需安装 CLI + 扩展）
- `agent-browser`：CLI for AI agents

**但这些对 Amazon 前台都会被拦**，只能用于自家后台等场景。

---

## 能力边界

| 能拿 | 拿不到 |
|---|---|
| ✅ 搜索排名（自然位 + 广告位）| ❌ 月销量（用 sellersprite）|
| ✅ 是否广告 + 多轮稳定性 | ❌ BSR（用 sellersprite）|
| ✅ 真实美元价格 | ❌ A+ / 视频（用 sellersprite）|
| ✅ 标题 / 评分 / 评论数 | ❌ 卖家名字（前台不返回，用 SP-API pricing）|
| ✅ 促销信息（Save X%）| ❌ 商品主图（HTML 里有但质量低）|

---

## 邮箱选择

| 邮编 | 城市 | 适用 |
|---|---|---|
| **10001** | **纽约** | **默认，最接近"平均美国买家"** |
| 90001 | 洛杉矶 | 西海岸 |
| 60601 | 芝加哥 | 中西部 |
| 77001 | 休斯顿 | 南部 |
| 33101 | 迈阿密 | 佛州 |

**统一用 10001**，除非要对比地区差异。

---

## 排序参数

| 老板说法 | 实际参数 | 对应前台 |
|---|---|---|
| **features** | **`relevanceblender`** | **Featured（默认）** |
| — | `price-asc-rank` | Price: Low to High |
| — | `price-desc-rank` | Price: High to Low |
| — | `review-rank` | Avg. Customer Review |
| — | `date-desc-rank` | Newest Arrivals |
| — | `exact-aware-popularity-rank` | Best Sellers |

**⚠️ 注意**：linkfox 的 `sort` 不支持 `features`（报 400）。但本脚本直接抓 HTML，URL 里用 `s=relevanceblender` 即默认 Featured。

---
name: amazon-serp-ads
description: 亚马逊前台 SERP 抓取 + 广告位分析。给一个关键词，连抓多轮（模拟刷新3次），统计哪些 ASIN 是稳定广告位、哪些是自然结果，同时拿到真实美元价格、排名、标题。当老板说「看广告位」「这个关键词谁在投广告」「SERP 分析」「前台搜索排名」「竞品广告位」时触发。
---

# 亚马逊 SERP + 广告位抓取

> **核心：两条通道。bsk（真实浏览器，最稳）优先；curl（裸 HTTP，最快）兜底。**

---

## 两条通道怎么选

| | **bsk（真实 Chrome）** | **curl（裸 HTTP）** |
|---|---|---|
| 脚本 | `bsk_serp.py` | `amz_serp_ads.py` |
| 反爬 | ✅ **完全正常**（真指纹+登录态）| ✅ 能过（但可能被降级）|
| 首轮广告数 | **12 个**（实测）| **0 个**（实测）|
| 速度 | 5-10 秒/轮 | 2 秒/轮 |
| 价格 | **自动美元** | 要加 cookie |
| 稳定性 | ✅ 3/3 成功 | 会 429/空页 |
| 依赖 | 需要 daemon + 扩展 | 无 |
| 登录态内容 | ✅ 能进卖家后台 | ❌ |

**决策**：
- **要广告位/要准 → bsk**
- **要快/bsk 不可用 → curl**
- **要登录态 → 只能 bsk**

---

## bsk 通道用法（推荐）

### 前置检查
```bash
export PATH="$HOME/.local/bin:$PATH"
export BSK_AUTO_START=0
bsk browsers      # 必须能看到 chrome，否则扩展没连上
```

如果 `browsers` 为空 → daemon 或扩展没起来：
```bash
# daemon 必须常驻（放在 run_in_background 任务里，不能停）
bsk daemon start --foreground
```

### 跑
```bash
python bsk_serp.py --keyword "dog bed" --rounds 3 --out result.json
python bsk_serp.py --url "https://www.amazon.com/s?k=dog+bed" --rounds 3
```

### 实测效果（`dog bed` 3 轮）
| 轮次 | 商品 | 广告 |
|---|---|---|
| 1 | **58** | **12** |
| 2 | 48 | 2 |
| 3 | 48 | 2 |

**合并 54 个 ASIN，12 个出现过广告。稳定广告位 2 个（3/3）。**

### 🔴 bsk 三个坑
| 坑 | 说明 |
|---|---|
| **session 会过期** | 约 7 分钟后失效（`requested resource does not exist`）。**每次任务新建，用完 `bsk session stop`** |
| **`get-html` 默认截断 512KB** | 必须 `--max-bytes 5000000`，否则解析出 0 个商品 |
| **每行命令都要 `BSK_AUTO_START=0`** | 否则它会尝试自启 daemon 然后失败 |

---

## curl 通道用法（兜底）

```bash
python amz_serp_ads.py --keyword "dog bed" --rounds 3 --gap 6
```

---

## 🔴 curl 的三个坑（实测踩过）

### ① linkfox 的 `amazon/search` 抓不到广告位
```
字段 sponsored 存在，但 48 个结果全是 false
```
**不要指望它**。

### ② 不加 Cookie → 价格是人民币
```
不加：a-offscreen">CNY 266.63      ← 按中国 IP 返回
加了：a-offscreen">$39.98           ← 正确美元
```
**必须带**：
```python
"Cookie": "i18n-prefs=USD; lc-main=en_US"
```

### ③ 广告位波动极大 → 单轮不可靠
实测 `dog bed` 连抓 3 轮：**0 / 14 / 2** 个广告。
**必须多轮合并**（老板说"刷新 3 次综合看"是对的）。

---

## 广告位判定口径

| 广告率 | 结论 | 含义 |
|---|---|---|
| **≥67%**（≥2/3 轮）| **稳定广告位** | 长期投、预算足，主要竞争对手 |
| 1/3 ～ 2/3 | 偶发广告位 | 试探性投放 / 分时段 |
| 0 | 自然结果 | 没投广告 |

---

## 技术实现要点

### 广告位 HTML 标记（两条通道通用）
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

**⚠️ 不要找 `sp-sponsored-result`**（0 次，已废弃）

### 价格提取
```python
re.search(r'a-offscreen">\$([\d,]+\.\d{2})</span>', card)
```

### 商品卡片切分
```python
re.split(r'(?=<div[^>]+data-component-type="s-search-result")', html)
```

---

## ⚠️ 路径坑（跨语言）
**bash 的 `/tmp` 和 Python 不通用**（Python 把 `/tmp/x` 解释成 `C:\tmp\x`）。
**跨语言传文件必须用 Windows 绝对路径**（如 `D:/workbuddy-ml/...`）。

---

## 能力边界

| 能拿 | 拿不到 |
|---|---|
| ✅ 搜索排名（自然位 + 广告位）| ❌ 月销量（用 sellersprite）|
| ✅ 是否广告 + 多轮稳定性 | ❌ BSR（用 sellersprite）|
| ✅ 真实美元价格 | ❌ A+ / 视频（用 sellersprite）|
| ✅ 标题 / 评分 / 评论数 | ❌ 卖家名字（前台不返回，用 SP-API pricing）|
| ✅ 促销信息（Save X%）| — |

---

## 邮编

| 邮编 | 城市 | 适用 |
|---|---|---|
| **10001** | **纽约** | **默认，最接近"平均美国买家"** |
| 90001 | 洛杉矶 | 西海岸 |
| 60601 | 芝加哥 | 中西部 |

**bsk 用的是老板 Chrome 里已设的地址**（实测就是 New York 10001）。

---

## 排序参数

| 老板说法 | 实际参数 | 对应前台 |
|---|---|---|
| **features** | **`relevanceblender`** | **Featured（默认）** |
| — | `price-asc-rank` | Price: Low to High |
| — | `price-desc-rank` | Price: High to Low |
| — | `review-rank` | Avg. Customer Review |
| — | `date-desc-rank` | Newest Arrivals |

**⚠️ linkfox 的 `sort` 不支持 `features`（报 400）。** URL 里用 `s=relevanceblender` 即默认 Featured。

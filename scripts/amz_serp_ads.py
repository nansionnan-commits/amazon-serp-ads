#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
亚马逊前台搜索 + 广告位抓取（不依赖 linkfox，直接 HTTP 抓 HTML）

老板的方法复现：
  开无痕浏览器 → 搜关键词 → 看广告位 → 刷新 3 次综合看

原理：
  Amazon 搜索页 HTML 里，广告商品卡片带 <span class="puis-sponsored-label-text">Sponsored</span>
  自然结果带 data-component-type="s-search-result"，无该标记

用法：
  python amz_serp_ads.py --keyword "dog bed"
  python amz_serp_ads.py --keyword "dog bed" --rounds 3        # 刷新3次综合看（老板的方法）
  python amz_serp_ads.py --keyword "dog bed" --zip 10001 --out result.json

输出：
  - 每个位置：排名 / ASIN / 是否广告 / 价格 / 标题
  - 多次抓取合并：广告位（出现≥2次 = 稳定广告位）
"""
import argparse
import json
import os
import random
import re
import time
import urllib.parse
import urllib.request

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# 广告位标记（实测有效）
AD_MARKERS = [
    "puis-sponsored-label-text",
    "sponsored-brand-label-info-desktop",
    'aria-label="Sponsored',
]


def fetch_serp(keyword, zip_code="10001", page=1, timeout=60, retry=2):
    """抓一页搜索结果 HTML"""
    qs = urllib.parse.urlencode({"k": keyword, "page": page, "ref": "nb_sb_noss"})
    url = f"https://www.amazon.com/s?{qs}"
    req = urllib.request.Request(url, headers={
        "User-Agent": random.choice(UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "no-cache",
        # 强制显示美元（否则按 IP 返回 CNY）
        "Cookie": "i18n-prefs=USD; lc-main=en_US",
    })
    last_err = ""
    for attempt in range(retry + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if raw[:2] == b"\x1f\x8b":
                    import gzip
                    raw = gzip.decompress(raw)
                html = raw.decode("utf-8", errors="ignore")
                # 被拦 / 空页 → 重试
                if len(html) < 50000 or "Sorry! Something went wrong" in html:
                    last_err = f"页面异常({len(html)} bytes)"
                    time.sleep(4 + attempt * 3)
                    continue
                return html
        except Exception as e:
            last_err = str(e)[:100]
            time.sleep(3 + attempt * 2)
    return {"_error": last_err or "多次重试仍失败"}

def parse_serp(html):
    """
    解析搜索结果，返回 [{position, asin, sponsored, title, price}]
    策略：按 data-asin 卡片切分，看每块里有没有广告标记
    """
    if isinstance(html, dict):
        return []

    # 用 data-component-type="s-search-result" 切商品卡片
    cards = re.split(r'(?=<div[^>]+data-component-type="s-search-result")', html)
    out = []
    pos = 0
    for c in cards[1:]:
        m = re.search(r'data-asin="(B0[A-Z0-9]{8})"', c)
        if not m:
            continue
        asin = m.group(1)
        pos += 1
        # 是否广告：卡片里有广告标记
        is_ad = any(mk in c for mk in AD_MARKERS)
        # 标题
        t = re.search(r'<h2[^>]*>.*?<span[^>]*>([^<]{10,200})</span>', c, re.S)
        title = re.sub(r"\s+", " ", t.group(1)).strip() if t else ""
        # 价格
        p = re.search(r'a-offscreen">\$([\d,]+\.\d{2})</span>', c)
        price = p.group(1).replace(",", "") if p else None
        out.append({
            "position": pos, "asin": asin, "sponsored": is_ad,
            "title": title[:80], "price": price,
        })
    return out


def merge_rounds(rounds):
    """多次抓取合并：统计每个 ASIN 出现次数 + 广告次数"""
    stat = {}
    for ri, rows in enumerate(rounds, 1):
        for r in rows:
            k = r["asin"]
            if k not in stat:
                stat[k] = {"asin": k, "title": r["title"], "price": r["price"],
                           "seen": 0, "ad_count": 0, "best_pos": 99, "positions": []}
            s = stat[k]
            s["seen"] += 1
            s["positions"].append(r["position"])
            s["best_pos"] = min(s["best_pos"], r["position"])
            if r["sponsored"]:
                s["ad_count"] += 1
    result = list(stat.values())
    for r in result:
        r["ad_rate"] = round(r["ad_count"] / len(rounds), 2)
        r["verdict"] = ("稳定广告位" if r["ad_rate"] >= 0.67
                        else "偶发广告位" if r["ad_rate"] > 0
                        else "自然结果")
    result.sort(key=lambda x: (x["best_pos"], -x["ad_rate"]))
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--zip", default="10001", help="邮编（默认纽约 10001）")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=1, help="抓几次（老板方法=3）")
    ap.add_argument("--gap", type=float, default=3.0, help="每轮间隔秒")
    ap.add_argument("--out")
    args = ap.parse_args()

    rounds = []
    for i in range(args.rounds):
        if i > 0:
            time.sleep(args.gap + random.uniform(0, 2))
        html = fetch_serp(args.keyword, args.zip, args.page)
        if isinstance(html, dict):
            print(f"第 {i+1} 轮失败: {html['_error']}")
            continue
        rows = parse_serp(html)
        ads = [r for r in rows if r["sponsored"]]
        print(f"第 {i+1} 轮: {len(rows)} 个结果，其中广告 {len(ads)} 个")
        rounds.append(rows)

    if not rounds:
        print("❌ 全部失败")
        return 1

    merged = merge_rounds(rounds)
    ads = [r for r in merged if r["ad_count"] > 0]

    print(f"\n{'='*80}")
    print(f"关键词：{args.keyword} | 邮编：{args.zip} | 抓了 {len(rounds)} 轮")
    print(f"总 ASIN：{len(merged)} | 出现过广告的：{len(ads)}")
    print(f"{'='*80}\n")

    print(f"{'排名':<6}{'ASIN':<14}{'广告':<8}{'价格':<9}标题")
    print("-" * 90)
    for r in merged[:30]:
        ad = f"{'✅广告' if r['ad_count'] else '—':<8}"
        print(f"{r['best_pos']:<6}{r['asin']:<14}{ad}${str(r['price'] or '-'):<8}{r['title'][:50]}")

    if len(rounds) > 1 and ads:
        print(f"\n【多轮综合分析】")
        print(f"{'ASIN':<14}{'广告次数':<10}{'广告率':<9}{'结论':<12}标题")
        print("-" * 90)
        for r in sorted(ads, key=lambda x: -x["ad_rate"]):
            print(f"{r['asin']:<14}{r['ad_count']}/{len(rounds):<8}{r['ad_rate']:<9.0%}"
                  f"{r['verdict']:<12}{r['title'][:40]}")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump({"keyword": args.keyword, "zip": args.zip,
                   "rounds": len(rounds), "results": merged},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n结果已存 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

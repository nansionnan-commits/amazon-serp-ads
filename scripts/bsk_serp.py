#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bsk 通道 —— 用老板已登录的真实 Chrome 抓 Amazon 前台（过反爬）

为什么用 bsk：
  curl 走中国 IP，Amazon 会限流/降级；Playwright headless 直接被拦（狗头错误页）。
  bsk 驱动的是用户真实登录的 Chrome，指纹/登录态/时区全对，Amazon 认。

前置条件：
  1. bsk CLI 在 PATH（默认 ~/.local/bin/bsk.exe）
  2. daemon 常驻：bsk daemon start --foreground（放在持久后台任务里）
  3. Chrome 装了 BrowserSkill 扩展且已启用连接

用法：
  python bsk_serp.py --keyword "dog bed" --rounds 3 --out result.json
  python bsk_serp.py --url "https://www.amazon.com/s?k=dog+bed" --rounds 3
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BSK = os.path.expanduser("~/.local/bin/bsk.exe")
if not os.path.exists(BSK):
    BSK = "bsk"

ENV = {**os.environ, "BSK_AUTO_START": "0"}


def run(args, timeout=120):
    """跑一条 bsk 命令，返回 (returncode, stdout+stderr)"""
    try:
        r = subprocess.run([BSK] + args, capture_output=True, text=True,
                           timeout=timeout, env=ENV, encoding="utf-8", errors="ignore")
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except FileNotFoundError:
        return -2, "bsk not found"


def session_start():
    """建会话，返回 session_id"""
    code, out = run(["session", "start", "--no-focus", "--json"], timeout=60)
    m = re.search(r'"session_id"\s*:\s*"([^"]+)"', out)
    if not m:
        raise RuntimeError(f"建 session 失败: {out[:200]}")
    return m.group(1)


def session_stop(sid):
    run(["session", "stop", sid], timeout=30)


def fetch_html(sid, url, out_path, max_bytes=5000000, timeout=120):
    """导航 + 拿完整 HTML"""
    code, out = run(["navigate", url, "--session", sid], timeout=timeout)
    if code != 0:
        return {"_error": out[:150]}
    # get-html 必须给 max_bytes，否则截断到 512KB
    code, out2 = run(["get-html", "--session", sid,
                      "--max-bytes", str(max_bytes), "--out", out_path], timeout=timeout)
    if code != 0:
        return {"_error": out2[:150]}
    if not os.path.exists(out_path):
        return {"_error": "HTML 文件未生成"}
    n = os.path.getsize(out_path)
    return {"bytes": n, "truncated": "truncated=true" in out2}


def crawl(keyword_or_url, rounds=3, gap=4, max_bytes=5000000, tmpdir=None):
    """
    用 bsk 抓 N 轮，返回 [(rows, meta)]，以及原始 HTML 路径
    """
    import amz_serp_ads as A

    url = (keyword_or_url if keyword_or_url.startswith("http")
           else f"https://www.amazon.com/s?k={keyword_or_url.replace(' ', '+')}")
    tmpdir = tmpdir or os.path.join(os.path.dirname(HERE), "_bsk_tmp")
    os.makedirs(tmpdir, exist_ok=True)

    sid = session_start()
    results, paths = [], []
    try:
        for i in range(1, rounds + 1):
            if i > 1:
                time.sleep(gap)
            p = os.path.join(tmpdir, f"bsk_r{i}.html")
            meta = fetch_html(sid, url, p, max_bytes=max_bytes)
            if "_error" in meta:
                print(f"  第 {i} 轮失败: {meta['_error']}")
                continue
            html = open(p, encoding="utf-8", errors="ignore").read()
            rows = A.parse_serp(html)
            ads = [r for r in rows if r["sponsored"]]
            print(f"  第 {i} 轮: HTML {meta['bytes']//1024}KB | "
                  f"商品 {len(rows)} | 广告 {len(ads)}"
                  f"{' | ⚠️截断' if meta['truncated'] else ''}")
            results.append(rows)
            paths.append(p)
    finally:
        session_stop(sid)

    return results, paths, url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword")
    ap.add_argument("--url")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--gap", type=float, default=4.0)
    ap.add_argument("--max-bytes", type=int, default=5000000)
    ap.add_argument("--out")
    args = ap.parse_args()

    target = args.url or args.keyword
    if not target:
        print("需要 --keyword 或 --url")
        return 1

    import amz_serp_ads as A

    print(f"bsk 抓取：{target}（{args.rounds} 轮）")
    rounds_data, paths, url = crawl(target, args.rounds, args.gap, args.max_bytes)
    if not rounds_data:
        print("❌ 全部失败")
        return 1

    merged = A.merge_rounds(rounds_data)
    ads = [r for r in merged if r["ad_count"] > 0]

    print(f"\n{'='*82}")
    print(f"合并 {len(merged)} 个 ASIN | {len(ads)} 个出现过广告")
    print(f"{'='*82}\n")
    print(f"{'ASIN':<14}{'广告':<7}{'广告率':<8}{'结论':<12}{'价格':<10}标题")
    print("-" * 88)
    for r in sorted(merged, key=lambda x: (x["best_pos"], -x["ad_rate"]))[:25]:
        ad = f"{r['ad_count']}/{len(rounds_data)}" if r["ad_count"] else "—"
        print(f"{r['asin']:<14}{ad:<7}{r['ad_rate']:<8.0%}{r['verdict']:<12}"
              f"${str(r['price'] or '-'):<9}{r['title'][:34]}")

    if ads:
        print(f"\n【稳定广告位（≥2/{len(rounds_data)} 轮）】")
        for r in [x for x in ads if x["ad_rate"] >= 0.67]:
            print(f"  {r['asin']}  ${r['price']}  {r['title'][:50]}")

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        json.dump({"url": url, "rounds": len(rounds_data),
                   "html_files": paths, "results": merged},
                  open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n结果已存 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宍粟市一宮町（地点番号 63251）の暑さ指数(WBGT)を環境省オープンデータから取得し、
速報値・シーズン集計・時系列グラフを埋め込んだ public/index.html を生成する。

依存: Python 標準ライブラリのみ（urllib, csv, json, datetime）。
出典: 環境省 熱中症予防情報サイト https://www.wbgt.env.go.jp/
"""

import csv
import io
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# ---- 設定 ----------------------------------------------------------------
POINT = "63251"                      # 一宮（宍粟市一宮町東市場）
POINT_NAME = "宍粟市一宮町（一宮）"
EST_URL = "https://www.wbgt.env.go.jp/est15WG/dl/wbgt_{point}_{ym}.csv"   # 実況値（月別）
FCST_URL = "https://www.wbgt.env.go.jp/prev15WG/dl/yohou_{point}.csv"     # 予測値
SEASON_MONTHS = range(5, 10)         # 5〜9月
GRAPH_DAYS = 7                       # 時系列グラフに出す直近の実況日数
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

JST = timezone(timedelta(hours=9))


# ---- ユーティリティ ------------------------------------------------------
def fetch(url):
    """URL を取得して文字列で返す。失敗時は None。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "wbgt-shiso-bot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def season_year(now):
    """対象シーズンの年を決める。
    5〜9月: 今年 / 10〜12月: 今年 / 1〜4月: 前年（直近に終わったシーズン）。"""
    return now.year if now.month >= 5 else now.year - 1


def parse_hhmm_date(date_str, time_str):
    """'2026/6/1' + '1:00'〜'24:00' を JST の datetime に変換。
    24:00 は当日扱いの便宜上、その日の23:59として扱い表示・集計上は当日に属させる。"""
    y, m, d = (int(x) for x in date_str.split("/"))
    hh, mm = (int(x) for x in time_str.split(":"))
    if hh == 24:
        # 24:00 はその日の終端。集計・グラフ上は当日 23:00台の次=翌0時相当だが、
        # 日別最高値の集計では当日に属させたいので date はそのまま、時刻のみ翌0時にする。
        base = datetime(y, m, d, 0, 0, tzinfo=JST) + timedelta(days=1)
        return base, f"{y:04d}/{m:02d}/{d:02d}"  # (実時刻, 集計対象日キー)
    return datetime(y, m, d, hh, mm, tzinfo=JST), f"{y:04d}/{m:02d}/{d:02d}"


def level_of(v):
    """WBGT値 → (レベル名, 色) を返す（環境省区分）。"""
    if v >= 31:
        return "危険", "#8b0000"
    if v >= 28:
        return "厳重警戒", "#ff4500"
    if v >= 25:
        return "警戒", "#ff8c00"
    if v >= 21:
        return "注意", "#e0a800"
    return "ほぼ安全", "#4a90d9"


# ---- 実況値の取得・集計 --------------------------------------------------
def load_observed(year):
    """シーズン各月の実況値を取得し、(観測点リスト, 日別最高, 最新速報) を返す。
    観測点 obs: [{"t": datetime, "v": float}], 集計用 daily: {dateKey: maxV},
    latest: (datetime, v) or None。"""
    obs = []                 # 時系列（実時刻つき）
    daily = {}               # 日別最高 {YYYY/MM/DD: max}
    latest = None            # (datetime, v) 最後の非空値

    for month in SEASON_MONTHS:
        ym = f"{year:04d}{month:02d}"
        text = fetch(EST_URL.format(point=POINT, ym=ym))
        if not text:
            continue
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            continue
        # 先頭行はヘッダー（Date,Time,63251）
        for row in rows[1:]:
            if len(row) < 3:
                continue
            date_str, time_str, val = row[0].strip(), row[1].strip(), row[2].strip()
            if not date_str or not time_str:
                continue
            if val == "" or val == "-":
                continue
            try:
                v = float(val)
            except ValueError:
                continue
            t, day_key = parse_hhmm_date(date_str, time_str)
            obs.append({"t": t, "v": v})
            daily[day_key] = max(daily.get(day_key, -99.0), v)
            if latest is None or t > latest[0]:
                latest = (t, v)

    obs.sort(key=lambda x: x["t"])
    return obs, daily, latest


def aggregate_days(daily, threshold):
    """日別最高が threshold 以上の日付（YYYY/MM/DD）を昇順で返す。"""
    days = [d for d, mx in daily.items() if mx >= threshold]
    days.sort()
    return days


# ---- 予測値の取得 --------------------------------------------------------
def load_forecast():
    """予測値CSVを取得し [{"t": datetime, "v": float}] を返す（値は×0.1）。"""
    text = fetch(FCST_URL.format(point=POINT))
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return []
    header = rows[0]
    data = rows[1]
    out = []
    for i in range(2, len(header)):
        code = header[i].strip()
        if len(code) < 10 or not code.isdigit():
            continue
        if i >= len(data):
            break
        raw = data[i].strip()
        if raw == "" or raw == "-":
            continue
        try:
            v = int(raw) / 10.0
        except ValueError:
            continue
        y, mo, d, hh = int(code[0:4]), int(code[4:6]), int(code[6:8]), int(code[8:10])
        if hh == 24:
            t = datetime(y, mo, d, 0, 0, tzinfo=JST) + timedelta(days=1)
        else:
            t = datetime(y, mo, d, hh, 0, tzinfo=JST)
        out.append({"t": t, "v": v})
    out.sort(key=lambda x: x["t"])
    return out


# ---- 時系列（グラフ用） --------------------------------------------------
def build_series(obs, fcst, now):
    """直近 GRAPH_DAYS 日の実況 + 予測を、共通ラベル軸で揃えて返す。"""
    cutoff = now - timedelta(days=GRAPH_DAYS)
    obs_pts = {p["t"]: p["v"] for p in obs if p["t"] >= cutoff}
    fc_pts = {p["t"]: p["v"] for p in fcst if p["t"] >= cutoff}

    all_t = sorted(set(obs_pts) | set(fc_pts))
    labels = [t.strftime("%-m/%-d %-H時") for t in all_t]
    obs_data = [obs_pts.get(t) for t in all_t]
    fc_data = [fc_pts.get(t) for t in all_t]
    return {"labels": labels, "observed": obs_data, "forecast": fc_data}


# ---- HTML 生成 -----------------------------------------------------------
def render_html(ctx):
    data_json = json.dumps(ctx["series"], ensure_ascii=False)
    days28 = ctx["days28"]
    days31 = ctx["days31"]

    def fmt_day(d):  # 2026/06/10 -> 6/10
        _, m, dd = d.split("/")
        return f"{int(m)}/{int(dd)}"

    list28 = "、".join(fmt_day(d) for d in days28) if days28 else "なし"
    list31 = "、".join(fmt_day(d) for d in days31) if days31 else "なし"

    if ctx["latest"]:
        lt, lv = ctx["latest"]
        lname, lcolor = level_of(lv)
        latest_html = f"""
      <div class="now-value" style="color:{lcolor}">{lv:.1f}</div>
      <div class="now-badge" style="background:{lcolor}">{lname}</div>
      <div class="now-time">{lt.strftime('%-m月%-d日 %-H時')}時点の速報値</div>"""
    else:
        latest_html = '<div class="now-time">速報値を取得できませんでした</div>'

    updated = ctx["updated"].strftime("%Y年%-m月%-d日 %-H:%M")
    season = ctx["season_year"]

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{POINT_NAME} 暑さ指数(WBGT)</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: -apple-system, "Hiragino Sans", "Noto Sans JP", sans-serif;
    color: #222; background: #fff; line-height: 1.6; padding: 16px; }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  h1 {{ font-size: 1.15rem; margin: 0 0 4px; }}
  .sub {{ color: #666; font-size: .8rem; margin-bottom: 16px; }}
  .card {{ border: 1px solid #e5e5e5; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
  .now {{ text-align: center; }}
  .now-label {{ font-size: .85rem; color: #666; }}
  .now-value {{ font-size: 3.4rem; font-weight: 800; line-height: 1.1; }}
  .now-badge {{ display: inline-block; color: #fff; font-weight: 700; padding: 4px 16px;
    border-radius: 999px; font-size: 1rem; margin: 4px 0; }}
  .now-time {{ font-size: .8rem; color: #666; }}
  .stats {{ display: flex; gap: 12px; }}
  .stat {{ flex: 1; text-align: center; border-radius: 10px; padding: 12px; color: #fff; }}
  .stat .n {{ font-size: 2.2rem; font-weight: 800; line-height: 1; }}
  .stat .l {{ font-size: .8rem; }}
  .stat.s28 {{ background: #ff4500; }}
  .stat.s31 {{ background: #8b0000; }}
  details {{ margin-top: 10px; font-size: .85rem; }}
  summary {{ cursor: pointer; color: #444; }}
  .daylist {{ margin-top: 6px; color: #555; }}
  .chart-box {{ position: relative; height: 320px; }}
  .legend-note {{ font-size: .75rem; color: #777; margin-top: 6px; }}
  footer {{ font-size: .72rem; color: #999; margin-top: 8px; text-align: center; }}
  footer a {{ color: #999; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{POINT_NAME}の暑さ指数（WBGT）</h1>
  <div class="sub">{season}年シーズン（5〜9月） ／ 最終更新 {updated}（自動）</div>

  <div class="card now">
    <div class="now-label">現在の暑さ指数（WBGT）</div>{latest_html}
  </div>

  <div class="card">
    <div class="stats">
      <div class="stat s28"><div class="n">{len(days28)}</div><div class="l">日<br>WBGT 28以上<br>（厳重警戒以上）</div></div>
      <div class="stat s31"><div class="n">{len(days31)}</div><div class="l">日<br>WBGT 31以上<br>（危険）</div></div>
    </div>
    <details><summary>28以上だった日（{len(days28)}日）</summary><div class="daylist">{list28}</div></details>
    <details><summary>31以上だった日（{len(days31)}日）</summary><div class="daylist">{list31}</div></details>
  </div>

  <div class="card">
    <div class="now-label" style="margin-bottom:8px;">直近{GRAPH_DAYS}日間の推移と予測</div>
    <div class="chart-box"><canvas id="chart"></canvas></div>
    <div class="legend-note">実線＝実況値／破線＝予測値。点線は警戒ライン（28・31）。</div>
  </div>

  <footer>
    出典：<a href="https://www.wbgt.env.go.jp/" target="_blank" rel="noopener">環境省 熱中症予防情報サイト</a><br>
    本ページは参考情報です。地点番号 {POINT}（{POINT_NAME}）。
  </footer>
</div>

<script id="series" type="application/json">{data_json}</script>
<script>
  const D = JSON.parse(document.getElementById('series').textContent);
  const n = D.labels.length;
  new Chart(document.getElementById('chart'), {{
    type: 'line',
    data: {{
      labels: D.labels,
      datasets: [
        {{ label: '実況', data: D.observed, borderColor: '#1565c0', backgroundColor: '#1565c0',
           spanGaps: false, tension: .3, pointRadius: 0, borderWidth: 2 }},
        {{ label: '予測', data: D.forecast, borderColor: '#ef6c00', backgroundColor: '#ef6c00',
           borderDash: [6,4], spanGaps: true, tension: .3, pointRadius: 0, borderWidth: 2 }},
        {{ label: '厳重警戒(28)', data: Array(n).fill(28), borderColor: 'rgba(255,69,0,.5)',
           borderDash: [3,3], pointRadius: 0, borderWidth: 1 }},
        {{ label: '危険(31)', data: Array(n).fill(31), borderColor: 'rgba(139,0,0,.5)',
           borderDash: [3,3], pointRadius: 0, borderWidth: 1 }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 8, font: {{ size: 10 }} }} }},
        y: {{ suggestedMin: 15, suggestedMax: 35, title: {{ display: true, text: 'WBGT (℃)' }} }}
      }}
    }}
  }});
</script>
</body>
</html>
"""


# ---- メイン --------------------------------------------------------------
def main():
    now = datetime.now(JST)
    year = season_year(now)

    obs, daily, latest = load_observed(year)
    fcst = load_forecast()
    series = build_series(obs, fcst, now)

    ctx = {
        "updated": now,
        "season_year": year,
        "latest": latest,
        "days28": aggregate_days(daily, 28),
        "days31": aggregate_days(daily, 31),
        "series": series,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render_html(ctx))

    print(f"generated: {out_path}")
    print(f"  season {year}, 28以上 {len(ctx['days28'])}日, 31以上 {len(ctx['days31'])}日, "
          f"latest {latest[1] if latest else 'N/A'}")


if __name__ == "__main__":
    main()

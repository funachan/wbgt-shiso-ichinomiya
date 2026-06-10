#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宍粟市一宮町（地点番号 63251）の暑さ指数(WBGT)を環境省オープンデータから取得し、
速報値・シーズン集計・時系列グラフ・年別推移グラフを埋め込んだ public/index.html を生成する。

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

# 今年（当シーズン）の実況値: est15WG/dl/wbgt_{point}_{YYYYMM}.csv
EST_URL = "https://www.wbgt.env.go.jp/est15WG/dl/wbgt_{point}_{ym}.csv"

# 過去年の確定値: mntr/final/{year}/wbgt_{year}/final_wbgt_{point}_{YYYYMM}.csv
# 列構成: Date,Time,WBGT,Tg（WBGTは3列目、値はそのまま℃）
HIST_URL = ("https://www.wbgt.env.go.jp/mntr/final/{year}/wbgt_{year}/"
            "final_wbgt_{point}_{ym}.csv")

FCST_URL = "https://www.wbgt.env.go.jp/prev15WG/dl/yohou_{point}.csv"   # 予測値
SEASON_MONTHS = range(5, 10)         # 5〜9月
HISTORY_START = 2010                 # 過去データの開始年
GRAPH_DAYS = 7                       # 時系列グラフの直近日数
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

JST = timezone(timedelta(hours=9))


# ---- ユーティリティ ------------------------------------------------------
def fetch(url):
    """URL を取得して文字列で返す。失敗時は None。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "wbgt-shiso-bot/1.0",
            "Referer": "https://www.wbgt.env.go.jp/",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def season_year(now):
    """対象シーズンの年を返す。1〜4月は前年シーズン扱い。"""
    return now.year if now.month >= 5 else now.year - 1


def parse_date_time(date_str, time_str):
    """'2026/6/1' + '1:00'〜'24:00' → (datetime JST, 日付キー YYYY/MM/DD)。"""
    y, m, d = (int(x) for x in date_str.split("/"))
    hh, mm = (int(x) for x in time_str.split(":"))
    if hh == 24:
        t = datetime(y, m, d, 0, 0, tzinfo=JST) + timedelta(days=1)
        return t, f"{y:04d}/{m:02d}/{d:02d}"
    return datetime(y, m, d, hh, mm, tzinfo=JST), f"{y:04d}/{m:02d}/{d:02d}"


def level_of(v):
    """WBGT値 → (レベル名, 色コード)（環境省区分）。"""
    if v >= 31:
        return "危険", "#8b0000"
    if v >= 28:
        return "厳重警戒", "#ff4500"
    if v >= 25:
        return "警戒", "#ff8c00"
    if v >= 21:
        return "注意", "#e0a800"
    return "ほぼ安全", "#4a90d9"


def parse_wbgt_csv(text, wbgt_col=2):
    """CSV テキストを解析して (日別最高dict, 時系列リスト, 最新値) を返す。
    wbgt_col: WBGT値が入る列インデックス（0始まり）。"""
    obs = []
    daily = {}
    latest = None
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    for row in rows[1:]:          # 1行目はヘッダー
        if len(row) <= wbgt_col:
            continue
        date_str = row[0].strip()
        time_str = row[1].strip()
        val = row[wbgt_col].strip()
        if not date_str or not time_str or val in ("", "-"):
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        t, day_key = parse_date_time(date_str, time_str)
        obs.append({"t": t, "v": v})
        daily[day_key] = max(daily.get(day_key, -99.0), v)
        if latest is None or t > latest[0]:
            latest = (t, v)
    return daily, obs, latest


# ---- 今シーズンの実況値 --------------------------------------------------
def load_current_season(year):
    """今年シーズン（5〜9月）の実況値を取得する。"""
    obs_all = []
    daily_all = {}
    latest = None
    for month in SEASON_MONTHS:
        ym = f"{year:04d}{month:02d}"
        text = fetch(EST_URL.format(point=POINT, ym=ym))
        if not text:
            continue
        # 今年のCSV列: Date,Time,{point番号}  → WBGT は列2
        daily, obs, lat = parse_wbgt_csv(text, wbgt_col=2)
        obs_all.extend(obs)
        for k, v in daily.items():
            daily_all[k] = max(daily_all.get(k, -99.0), v)
        if lat and (latest is None or lat[0] > latest[0]):
            latest = lat
    obs_all.sort(key=lambda x: x["t"])
    return obs_all, daily_all, latest


# ---- 過去年の確定値（年別集計用） ----------------------------------------
def load_year_summary(year):
    """過去1年分（5〜9月）の日別最高を集計して (days28, days31) を返す。"""
    daily_all = {}
    for month in SEASON_MONTHS:
        ym = f"{year:04d}{month:02d}"
        text = fetch(HIST_URL.format(year=year, point=POINT, ym=ym))
        if not text:
            continue
        # 確定値CSV列: Date,Time,WBGT,Tg → WBGT は列2
        daily, _, _ = parse_wbgt_csv(text, wbgt_col=2)
        for k, v in daily.items():
            daily_all[k] = max(daily_all.get(k, -99.0), v)
    days28 = sum(1 for v in daily_all.values() if v >= 28)
    days31 = sum(1 for v in daily_all.values() if v >= 31)
    return days28, days31


def load_history(current_year):
    """HISTORY_START 〜 current_year-1 の年別集計を返す。
    [{year, days28, days31}, ...]（欠損年はスキップ）。"""
    results = []
    for year in range(HISTORY_START, current_year):
        d28, d31 = load_year_summary(year)
        results.append({"year": year, "days28": d28, "days31": d31})
        print(f"  history {year}: 28以上={d28}日, 31以上={d31}日")
    return results


# ---- 予測値 --------------------------------------------------------------
def load_forecast():
    """予測値CSVを取得し [{t, v}] を返す（値は×0.1）。"""
    text = fetch(FCST_URL.format(point=POINT))
    if not text:
        return []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return []
    header, data = rows[0], rows[1]
    out = []
    for i in range(2, len(header)):
        code = header[i].strip()
        if len(code) < 10 or not code.isdigit():
            continue
        if i >= len(data):
            break
        raw = data[i].strip()
        if raw in ("", "-"):
            continue
        try:
            v = int(raw) / 10.0
        except ValueError:
            continue
        y, mo, d, hh = int(code[0:4]), int(code[4:6]), int(code[6:8]), int(code[8:10])
        t = (datetime(y, mo, d, 0, 0, tzinfo=JST) + timedelta(days=1)
             if hh == 24 else datetime(y, mo, d, hh, 0, tzinfo=JST))
        out.append({"t": t, "v": v})
    out.sort(key=lambda x: x["t"])
    return out


# ---- 時系列グラフデータ --------------------------------------------------
def build_series(obs, fcst, now):
    """直近 GRAPH_DAYS 日の実況 + 予測を共通軸で揃える。"""
    cutoff = now - timedelta(days=GRAPH_DAYS)
    obs_pts = {p["t"]: p["v"] for p in obs if p["t"] >= cutoff}
    fc_pts = {p["t"]: p["v"] for p in fcst if p["t"] >= cutoff}
    all_t = sorted(set(obs_pts) | set(fc_pts))
    return {
        "labels": [t.strftime("%-m/%-d %-H時") for t in all_t],
        "observed": [obs_pts.get(t) for t in all_t],
        "forecast": [fc_pts.get(t) for t in all_t],
    }


# ---- HTML 生成 -----------------------------------------------------------
def render_html(ctx):
    series_json = json.dumps(ctx["series"], ensure_ascii=False)
    history_json = json.dumps(ctx["history"], ensure_ascii=False)

    days28, days31 = ctx["days28"], ctx["days31"]

    def fmt_day(d):
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
  .card-title {{ font-size: .88rem; font-weight: 700; color: #444; margin-bottom: 10px; }}
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
  .daylist {{ margin-top: 6px; color: #555; line-height: 1.8; }}
  .chart-box {{ position: relative; height: 300px; }}
  .chart-box-lg {{ position: relative; height: 340px; }}
  .legend-note {{ font-size: .75rem; color: #777; margin-top: 6px; }}
  footer {{ font-size: .72rem; color: #999; margin-top: 8px; text-align: center; }}
  footer a {{ color: #999; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{POINT_NAME}の暑さ指数（WBGT）</h1>
  <div class="sub">{season}年シーズン（5〜9月） ／ 最終更新 {updated}（自動）</div>

  <!-- 速報値 -->
  <div class="card now">
    <div class="now-label">現在の暑さ指数（WBGT）</div>{latest_html}
  </div>

  <!-- 今シーズン集計 -->
  <div class="card">
    <div class="card-title">{season}年シーズンの集計（5〜9月）</div>
    <div class="stats">
      <div class="stat s28">
        <div class="n">{len(days28)}</div>
        <div class="l">日<br>WBGT 28以上<br>（厳重警戒以上）</div>
      </div>
      <div class="stat s31">
        <div class="n">{len(days31)}</div>
        <div class="l">日<br>WBGT 31以上<br>（危険）</div>
      </div>
    </div>
    <details>
      <summary>28以上だった日（{len(days28)}日）</summary>
      <div class="daylist">{list28}</div>
    </details>
    <details>
      <summary>31以上だった日（{len(days31)}日）</summary>
      <div class="daylist">{list31}</div>
    </details>
  </div>

  <!-- 直近の時系列グラフ -->
  <div class="card">
    <div class="card-title">直近{GRAPH_DAYS}日間の推移と予測</div>
    <div class="chart-box"><canvas id="chart-trend"></canvas></div>
    <div class="legend-note">実線＝実況値 ／ 破線＝予測値 ／ 点線は警戒ライン（28・31）</div>
  </div>

  <!-- 年別推移グラフ -->
  <div class="card">
    <div class="card-title">年別 暑さ指数 超過日数の推移（{HISTORY_START}〜{season}年）</div>
    <div class="chart-box-lg"><canvas id="chart-history"></canvas></div>
    <div class="legend-note">
      各年の5〜9月でWBGTが28以上・31以上となった日数（日最高値で判定）。
      {season}年は速報値をもとに集計中。
    </div>
  </div>

  <footer>
    出典：<a href="https://www.wbgt.env.go.jp/" target="_blank" rel="noopener">環境省 熱中症予防情報サイト</a><br>
    本ページは参考情報です。地点番号 {POINT}（{POINT_NAME}）。
  </footer>
</div>

<script id="series-data" type="application/json">{series_json}</script>
<script id="history-data" type="application/json">{history_json}</script>
<script>
(function() {{
  // ---- 時系列グラフ ----
  const D = JSON.parse(document.getElementById('series-data').textContent);
  const n = D.labels.length;
  new Chart(document.getElementById('chart-trend'), {{
    type: 'line',
    data: {{
      labels: D.labels,
      datasets: [
        {{ label: '実況', data: D.observed, borderColor: '#1565c0',
           spanGaps: false, tension: .3, pointRadius: 0, borderWidth: 2 }},
        {{ label: '予測', data: D.forecast, borderColor: '#ef6c00',
           borderDash: [6,4], spanGaps: true, tension: .3, pointRadius: 0, borderWidth: 2 }},
        {{ label: '厳重警戒(28)', data: Array(n).fill(28), borderColor: 'rgba(255,69,0,.45)',
           borderDash: [3,3], pointRadius: 0, borderWidth: 1.5 }},
        {{ label: '危険(31)', data: Array(n).fill(31), borderColor: 'rgba(139,0,0,.45)',
           borderDash: [3,3], pointRadius: 0, borderWidth: 1.5 }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{ legend: {{ labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
      scales: {{
        x: {{ ticks: {{ maxTicksLimit: 8, font: {{ size: 10 }} }} }},
        y: {{ suggestedMin: 15, suggestedMax: 35,
             title: {{ display: true, text: 'WBGT (℃)' }} }}
      }}
    }}
  }});

  // ---- 年別推移グラフ ----
  const H = JSON.parse(document.getElementById('history-data').textContent);
  const years = H.map(r => r.year + '年');
  const d28   = H.map(r => r.days28);
  const d31   = H.map(r => r.days31);
  new Chart(document.getElementById('chart-history'), {{
    type: 'bar',
    data: {{
      labels: years,
      datasets: [
        {{ label: 'WBGT 28以上（厳重警戒以上）の日数',
           data: d28, backgroundColor: 'rgba(255,69,0,.75)', borderRadius: 3 }},
        {{ label: 'WBGT 31以上（危険）の日数',
           data: d31, backgroundColor: 'rgba(139,0,0,.85)', borderRadius: 3 }}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ boxWidth: 14, font: {{ size: 11 }} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y + '日' }} }}
      }},
      scales: {{
        x: {{ ticks: {{ font: {{ size: 10 }} }} }},
        y: {{ beginAtZero: true, title: {{ display: true, text: '日数（日）' }},
             ticks: {{ stepSize: 5 }} }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>
"""


# ---- メイン --------------------------------------------------------------
def main():
    now = datetime.now(JST)
    year = season_year(now)

    print(f"=== WBGT build {now.strftime('%Y-%m-%d %H:%M')} JST ===")

    print("今シーズンの実況値を取得中...")
    obs, daily, latest = load_current_season(year)

    print("予測値を取得中...")
    fcst = load_forecast()
    series = build_series(obs, fcst, now)

    print(f"過去データを取得中（{HISTORY_START}〜{year - 1}年）...")
    history_past = load_history(year)

    # 今年分を末尾に追加（集計途中）
    days28_list = [d for d, mx in daily.items() if mx >= 28]
    days31_list = [d for d, mx in daily.items() if mx >= 31]
    history = history_past + [{"year": year, "days28": len(days28_list), "days31": len(days31_list)}]

    ctx = {
        "updated": now,
        "season_year": year,
        "latest": latest,
        "days28": sorted(days28_list),
        "days31": sorted(days31_list),
        "series": series,
        "history": history,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(render_html(ctx))

    print(f"generated: {out_path}")
    print(f"  今シーズン: 28以上 {len(days28_list)}日, 31以上 {len(days31_list)}日, latest {latest[1] if latest else 'N/A'}")
    print(f"  年別履歴: {len(history)}年分")


if __name__ == "__main__":
    main()

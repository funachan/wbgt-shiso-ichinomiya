#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宍粟市一宮町（地点番号 63251）の暑さ指数(WBGT)を環境省オープンデータから取得し、
速報値・シーズン集計・時系列グラフ・年別推移グラフを埋め込んだ public/index.html を生成する。

過去年の確定値は history_cache.json にキャッシュし、毎時の更新は最小限のリクエストで済む。

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
POINT = "63251"
POINT_NAME = "宍粟市一宮町（一宮）"

EST_URL = "https://www.wbgt.env.go.jp/est15WG/dl/wbgt_{point}_{ym}.csv"
HIST_URL = ("https://www.wbgt.env.go.jp/mntr/final/{year}/wbgt_{year}/"
            "final_wbgt_{point}_{ym}.csv")
FCST_URL = "https://www.wbgt.env.go.jp/prev15WG/dl/yohou_{point}.csv"

SEASON_MONTHS = range(5, 10)
HISTORY_START = 2010
GRAPH_DAYS = 7

# 夏休み期間（この期間を除いた日数を別途集計）
# 形式: {year: (開始日 "YYYY/MM/DD", 終了日 "YYYY/MM/DD")}
SUMMER_BREAKS = {
    2023: ("2023/07/21", "2023/08/31"),
    2024: ("2024/07/20", "2024/08/31"),
    2025: ("2025/07/19", "2025/08/31"),
}
# 日別データを保持する年（夏休み除外集計に必要）
DAILY_DETAIL_YEARS = set(SUMMER_BREAKS.keys())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "public")
CACHE_FILE = os.path.join(BASE_DIR, "history_cache.json")

JST = timezone(timedelta(hours=9))


# ---- ユーティリティ ------------------------------------------------------
def fetch(url):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "wbgt-shiso-bot/1.0",
            "Referer": "https://www.wbgt.env.go.jp/",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def season_year(now):
    return now.year if now.month >= 5 else now.year - 1


def parse_date_time(date_str, time_str):
    y, m, d = (int(x) for x in date_str.split("/"))
    hh, mm = (int(x) for x in time_str.split(":"))
    if hh == 24:
        t = datetime(y, m, d, 0, 0, tzinfo=JST) + timedelta(days=1)
        return t, f"{y:04d}/{m:02d}/{d:02d}"
    return datetime(y, m, d, hh, mm, tzinfo=JST), f"{y:04d}/{m:02d}/{d:02d}"


def level_of(v):
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
    obs = []
    daily = {}
    latest = None
    reader = csv.reader(io.StringIO(text))
    for row in list(reader)[1:]:
        if len(row) <= wbgt_col:
            continue
        date_str, time_str = row[0].strip(), row[1].strip()
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
    obs_all, daily_all, latest = [], {}, None
    for month in SEASON_MONTHS:
        ym = f"{year:04d}{month:02d}"
        text = fetch(EST_URL.format(point=POINT, ym=ym))
        if not text:
            continue
        daily, obs, lat = parse_wbgt_csv(text, wbgt_col=2)
        obs_all.extend(obs)
        for k, v in daily.items():
            daily_all[k] = max(daily_all.get(k, -99.0), v)
        if lat and (latest is None or lat[0] > latest[0]):
            latest = lat
    obs_all.sort(key=lambda x: x["t"])
    return obs_all, daily_all, latest


# ---- 夏休み除外ユーティリティ --------------------------------------------
def in_summer_break(day_key, year):
    """day_key (YYYY/MM/DD) が当該年の夏休み期間内なら True。"""
    if year not in SUMMER_BREAKS:
        return False
    brk_start, brk_end = SUMMER_BREAKS[year]
    return brk_start <= day_key <= brk_end


def count_excluding_break(daily, year, threshold):
    """日別最高dict から夏休みを除いたthreshold以上の日数を返す。"""
    return sum(1 for d, v in daily.items()
               if v >= threshold and not in_summer_break(d, year))


def monthly_breakdown(daily, year):
    """日別最高dict から月別の集計を返す。
    戻り値: {月(int): {"days28": n, "days31": n, "days28_nb": n, "days31_nb": n}}
    _nb = no_break（夏休み除外）"""
    result = {}
    for day_key, v in daily.items():
        m = int(day_key.split("/")[1])
        if m not in result:
            result[m] = {"days28": 0, "days31": 0, "days28_nb": 0, "days31_nb": 0}
        is_break = in_summer_break(day_key, year)
        if v >= 28:
            result[m]["days28"] += 1
            if not is_break:
                result[m]["days28_nb"] += 1
        if v >= 31:
            result[m]["days31"] += 1
            if not is_break:
                result[m]["days31_nb"] += 1
    return result


# ---- 過去年の確定値（キャッシュ付き） ------------------------------------
def load_year_summary_remote(year):
    """5〜9月の日別最高WBGTを取得して返す。"""
    daily_all = {}
    for month in SEASON_MONTHS:
        ym = f"{year:04d}{month:02d}"
        text = fetch(HIST_URL.format(year=year, point=POINT, ym=ym))
        if not text:
            continue
        daily, _, _ = parse_wbgt_csv(text, wbgt_col=2)
        for k, v in daily.items():
            daily_all[k] = max(daily_all.get(k, -99.0), v)
    return daily_all


def load_history_cached(current_year):
    """キャッシュJSONから履歴を読み込み、未取得の年だけリモート取得して追記する。"""
    cache = {}
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)

    changed = False
    for year in range(HISTORY_START, current_year):
        key = str(year)
        need_daily = year in DAILY_DETAIL_YEARS
        # 日別データが必要な年でキャッシュに daily がなければ再取得
        if key in cache and not (need_daily and "daily" not in cache[key]):
            continue
        print(f"  fetch history {year}...")
        daily_all = load_year_summary_remote(year)
        entry = {
            "days28": sum(1 for v in daily_all.values() if v >= 28),
            "days31": sum(1 for v in daily_all.values() if v >= 31),
        }
        if need_daily:
            entry["daily"] = daily_all   # 夏休み除外計算用に日別データを保持
        cache[key] = entry
        changed = True
        print(f"    {year}: 28以上={entry['days28']}日, 31以上={entry['days31']}日")

    if changed:
        os.makedirs(BASE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"  キャッシュ更新: {CACHE_FILE}")

    results = []
    for year in range(HISTORY_START, current_year):
        key = str(year)
        if key not in cache:
            continue
        entry = cache[key]
        row = {
            "year": year,
            "days28": entry["days28"],
            "days31": entry["days31"],
        }
        if "daily" in entry:
            daily = entry["daily"]
            row["days28_no_break"] = count_excluding_break(daily, year, 28)
            row["days31_no_break"] = count_excluding_break(daily, year, 31)
            row["monthly"] = monthly_breakdown(daily, year)
        results.append(row)
    return results


# ---- 予測値 --------------------------------------------------------------
def load_forecast():
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


# ---- 時系列グラフ --------------------------------------------------------
def build_series(obs, fcst, now):
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
def make_break_label(year):
    """夏休み期間の表示ラベルを返す。"""
    if year not in SUMMER_BREAKS:
        return ""
    s, e = SUMMER_BREAKS[year]
    def fmt(d):
        _, m, dd = d.split("/")
        return f"{int(m)}/{int(dd)}"
    return f"（夏休み {fmt(s)}〜{fmt(e)} 除く）"


def render_html(ctx):
    series_json = json.dumps(ctx["series"], ensure_ascii=False)
    history_json = json.dumps(ctx["history"], ensure_ascii=False)

    days28, days31 = ctx["days28"], ctx["days31"]
    break_stats = ctx["break_stats"]

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

    # 月別グラフ用データ（break_statsの各年の monthly を整形）
    month_labels = [f"{m}月" for m in SEASON_MONTHS]
    monthly_chart_data = []
    for r in break_stats:
        mo = r.get("monthly", {})
        monthly_chart_data.append({
            "year": r["year"],
            "d28":  [mo.get(m, {}).get("days28", 0)    for m in SEASON_MONTHS],
            "d31":  [mo.get(m, {}).get("days31", 0)    for m in SEASON_MONTHS],
            "d28nb":[mo.get(m, {}).get("days28_nb", 0) for m in SEASON_MONTHS],
            "d31nb":[mo.get(m, {}).get("days31_nb", 0) for m in SEASON_MONTHS],
        })
    monthly_json = json.dumps({"labels": month_labels, "years": monthly_chart_data},
                               ensure_ascii=False)

    # 月別テーブルの行を生成（行=月、列=年）
    detail_years = [r["year"] for r in break_stats]
    month_rows_html_28 = ""
    month_rows_html_31 = ""
    for m in SEASON_MONTHS:
        mn = f"{m}月"
        cells28 = ""
        cells31 = ""
        for r in break_stats:
            mo = r.get("monthly", {}).get(m, {})
            d28    = mo.get("days28", 0)
            d28nb  = mo.get("days28_nb", 0)
            d31    = mo.get("days31", 0)
            d31nb  = mo.get("days31_nb", 0)
            brk_s, brk_e = SUMMER_BREAKS.get(r["year"], ("", ""))
            # 夏休みが含まれる月かどうか
            has_break = (brk_s and int(brk_s.split("/")[1]) <= m <= int(brk_e.split("/")[1]))
            if has_break:
                cells28 += f'<td class="c28">{d28}日<br><small style="color:#888">除:{d28nb}日</small></td>'
                cells31 += f'<td class="c31">{d31}日<br><small style="color:#888">除:{d31nb}日</small></td>'
            else:
                cells28 += f'<td class="c28">{d28}日</td>'
                cells31 += f'<td class="c31">{d31}日</td>'
        month_rows_html_28 += f"<tr><td class='yr'>{mn}</td>{cells28}</tr>\n"
        month_rows_html_31 += f"<tr><td class='yr'>{mn}</td>{cells31}</tr>\n"

    year_headers = "".join(f"<th>{y}年</th>" for y in detail_years)

    # 夏休み除外テーブルの行を生成
    break_rows = []
    for r in break_stats:
        y = r["year"]
        brk = SUMMER_BREAKS.get(y, ("", ""))
        def _fmt(d):
            _, m, dd = d.split("/")
            return f"{int(m)}/{int(dd)}"
        brk_label = f"{_fmt(brk[0])}〜{_fmt(brk[1])}" if brk[0] else "—"
        break_rows.append(
            f'<tr>'
            f'<td class="yr">{y}年</td>'
            f'<td style="font-size:.8rem;color:#666">{brk_label}</td>'
            f'<td class="c28">{r["days28"]}日</td>'
            f'<td class="c28">{r["days28_no_break"]}日</td>'
            f'<td class="c31">{r["days31"]}日</td>'
            f'<td class="c31">{r["days31_no_break"]}日</td>'
            f'</tr>'
        )
    break_rows_html = "\n        ".join(break_rows) if break_rows else '<tr><td colspan="6">データなし</td></tr>'

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
  .break-table {{ width: 100%; border-collapse: collapse; font-size: .85rem; margin-top: 8px; }}
  .break-table th {{ background: #f5f5f5; padding: 6px 10px; text-align: center;
    border-bottom: 2px solid #ddd; font-weight: 700; }}
  .break-table td {{ padding: 7px 10px; text-align: center; border-bottom: 1px solid #eee; }}
  .break-table tr:last-child td {{ border-bottom: none; }}
  .break-table .yr {{ text-align: left; font-weight: 600; }}
  .break-table .c28 {{ color: #d63000; font-weight: 700; }}
  .break-table .c31 {{ color: #8b0000; font-weight: 700; }}
  .break-note {{ font-size: .75rem; color: #888; margin-top: 6px; line-height: 1.6; }}
  .tab-btns {{ display: flex; gap: 6px; margin-bottom: 10px; }}
  .tab-btn {{ background: #f0f0f0; border: none; border-radius: 6px; padding: 5px 14px;
    font-size: .82rem; cursor: pointer; }}
  .tab-btn.active {{ background: #1565c0; color: #fff; font-weight: 700; }}
  .tab-panel {{ display: none; }}
  .tab-panel.active {{ display: block; }}
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

  <div class="card">
    <div class="card-title">直近{GRAPH_DAYS}日間の推移と予測</div>
    <div class="chart-box"><canvas id="chart-trend"></canvas></div>
    <div class="legend-note">実線＝実況値 ／ 破線＝予測値 ／ 点線は警戒ライン（28・31）</div>
  </div>

  <!-- 夏休み除外集計（直近3年）+ 月別 -->
  <div class="card">
    <div class="card-title">夏休みを除いた暑さ指数 超過日数（直近3年）</div>
    <div class="tab-btns">
      <button class="tab-btn active" onclick="switchTab(this,'tab-season')">シーズン合計</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-m28')">月別 28以上</button>
      <button class="tab-btn" onclick="switchTab(this,'tab-m31')">月別 31以上</button>
    </div>

    <!-- シーズン合計 -->
    <div id="tab-season" class="tab-panel active">
      <table class="break-table">
        <thead><tr>
          <th>年</th><th>夏休み期間</th>
          <th class="c28">28以上<br>全期間</th><th class="c28">28以上<br>夏休み除く</th>
          <th class="c31">31以上<br>全期間</th><th class="c31">31以上<br>夏休み除く</th>
        </tr></thead>
        <tbody>{break_rows_html}</tbody>
      </table>
    </div>

    <!-- 月別 28以上 -->
    <div id="tab-m28" class="tab-panel">
      <table class="break-table">
        <thead><tr><th>月</th>{year_headers}</tr></thead>
        <tbody>{month_rows_html_28}</tbody>
      </table>
      <div class="break-note">夏休みが含まれる月は「全数／除:夏休み除く日数」を表示。</div>
    </div>

    <!-- 月別 31以上 -->
    <div id="tab-m31" class="tab-panel">
      <table class="break-table">
        <thead><tr><th>月</th>{year_headers}</tr></thead>
        <tbody>{month_rows_html_31}</tbody>
      </table>
      <div class="break-note">夏休みが含まれる月は「全数／除:夏休み除く日数」を表示。</div>
    </div>

    <div class="break-note" style="margin-top:10px">
      夏休み期間は宍粟市立学校の夏季休業日に基づく目安。集計対象：5〜9月の日最高WBGT。
    </div>
  </div>

  <!-- 月別推移グラフ（直近3年） -->
  <div class="card">
    <div class="card-title">月別 超過日数グラフ（直近3年比較）</div>
    <div class="tab-btns">
      <button class="tab-btn active" onclick="switchTab(this,'mg-28')">WBGT 28以上</button>
      <button class="tab-btn" onclick="switchTab(this,'mg-31')">WBGT 31以上</button>
    </div>
    <div id="mg-28" class="tab-panel active">
      <div class="chart-box"><canvas id="chart-monthly-28"></canvas></div>
    </div>
    <div id="mg-31" class="tab-panel">
      <div class="chart-box"><canvas id="chart-monthly-31"></canvas></div>
    </div>
    <div class="legend-note">各年の5〜9月の月別超過日数（全期間。夏休みを含む）。</div>
  </div>

  <!-- 年別推移グラフ -->
  <div class="card">
    <div class="card-title">年別 暑さ指数 超過日数の推移（{HISTORY_START}〜{season}年）</div>
    <div class="chart-box-lg"><canvas id="chart-history"></canvas></div>
    <div class="legend-note">
      各年の5〜9月でWBGTが28以上・31以上となった日数（日最高値で判定）。
      {season}年は速報値をもとに集計中。出典：環境省 熱中症予防情報サイト
    </div>
  </div>

  <footer>
    出典：<a href="https://www.wbgt.env.go.jp/" target="_blank" rel="noopener">環境省 熱中症予防情報サイト</a><br>
    本ページは参考情報です。地点番号 {POINT}（{POINT_NAME}）。
  </footer>
</div>

<script id="series-data" type="application/json">{series_json}</script>
<script id="history-data" type="application/json">{history_json}</script>
<script id="monthly-data" type="application/json">{monthly_json}</script>
<script>
function switchTab(btn, panelId) {{
  const card = btn.closest('.card');
  card.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  card.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(panelId).classList.add('active');
}}

(function() {{
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

  const H = JSON.parse(document.getElementById('history-data').textContent);
  new Chart(document.getElementById('chart-history'), {{
    type: 'bar',
    data: {{
      labels: H.map(r => r.year + '年'),
      datasets: [
        {{ label: 'WBGT 28以上（厳重警戒以上）の日数',
           data: H.map(r => r.days28),
           backgroundColor: 'rgba(255,69,0,.75)', borderRadius: 3 }},
        {{ label: 'WBGT 31以上（危険）の日数',
           data: H.map(r => r.days31),
           backgroundColor: 'rgba(139,0,0,.85)', borderRadius: 3 }}
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
        y: {{ beginAtZero: true,
             title: {{ display: true, text: '日数（日）' }},
             ticks: {{ stepSize: 5 }} }}
      }}
    }}
  }});

  // ---- 月別グラフ ----
  const M = JSON.parse(document.getElementById('monthly-data').textContent);
  const colors = ['#1565c0','#2e7d32','#c62828'];
  const alphas = ['rgba(21,101,192,.75)','rgba(46,125,50,.75)','rgba(198,40,40,.75)'];

  function makeMonthlyChart(canvasId, field) {{
    new Chart(document.getElementById(canvasId), {{
      type: 'bar',
      data: {{
        labels: M.labels,
        datasets: M.years.map((r, i) => ({{
          label: r.year + '年',
          data: r[field],
          backgroundColor: alphas[i % alphas.length],
          borderColor: colors[i % colors.length],
          borderWidth: 1, borderRadius: 3,
        }}))
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        interaction: {{ mode: 'index', intersect: false }},
        plugins: {{
          legend: {{ labels: {{ boxWidth: 14, font: {{ size: 11 }} }} }},
          tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y + '日' }} }}
        }},
        scales: {{
          x: {{ ticks: {{ font: {{ size: 11 }} }} }},
          y: {{ beginAtZero: true, title: {{ display: true, text: '日数（日）' }},
               ticks: {{ stepSize: 5 }} }}
        }}
      }}
    }});
  }}

  makeMonthlyChart('chart-monthly-28', 'd28');
  makeMonthlyChart('chart-monthly-31', 'd31');
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

    print(f"過去データを確認中（キャッシュ: {CACHE_FILE}）...")
    history_past = load_history_cached(year)

    days28_list = sorted(d for d, mx in daily.items() if mx >= 28)
    days31_list = sorted(d for d, mx in daily.items() if mx >= 31)

    cur_row = {"year": year, "days28": len(days28_list), "days31": len(days31_list)}
    if year in DAILY_DETAIL_YEARS:
        cur_row["days28_no_break"] = count_excluding_break(daily, year, 28)
        cur_row["days31_no_break"] = count_excluding_break(daily, year, 31)
        cur_row["monthly"] = monthly_breakdown(daily, year)
    history = history_past + [cur_row]

    # 夏休み除外集計・月別データがある年（直近3年分）
    break_stats = [r for r in history if "days28_no_break" in r]

    ctx = {
        "updated": now,
        "season_year": year,
        "latest": latest,
        "days28": days28_list,
        "days31": days31_list,
        "series": series,
        "history": history,
        "break_stats": break_stats,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(ctx))

    print(f"generated: {OUT_DIR}/index.html")
    print(f"  今シーズン: 28以上 {len(days28_list)}日, 31以上 {len(days31_list)}日")
    print(f"  年別履歴: {len(history)}年分")


if __name__ == "__main__":
    main()

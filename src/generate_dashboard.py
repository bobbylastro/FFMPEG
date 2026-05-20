"""Génère docs/index.html — dashboard analytics GitHub Pages."""
import json
import os
from datetime import datetime

ANALYTICS_DIR = "data/analytics"
OUTPUT_PATH   = "docs/index.html"

GAME_COLORS = {
    "valorant":          "#FF4655",
    "counter-strike-2":  "#F0A500",
    "league-of-legends": "#C89B3C",
    "apex-legends":      "#FC4422",
    "rocket-league":     "#3BADF8",
    "r6-siege":          "#FF6A00",
}


def _load_all() -> dict:
    data = {}
    if not os.path.exists(ANALYTICS_DIR):
        return data
    for fname in sorted(os.listdir(ANALYTICS_DIR)):
        if not fname.endswith(".json") or fname == "channels.json":
            continue
        slug = fname[:-5]
        with open(os.path.join(ANALYTICS_DIR, fname)) as f:
            records = json.load(f)
        if records:
            data[slug] = records
    return data


def _load_channels() -> dict:
    path = os.path.join(ANALYTICS_DIR, "channels.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _game_name(slug: str, records: list) -> str:
    for r in records:
        if r.get("game"):
            return r["game"]
    return slug.replace("-", " ").title()


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _chart_js(chart_id: str, labels: list, values: list, color: str, label: str) -> str:
    return f"""
    new Chart(document.getElementById('{chart_id}'), {{
        type: 'bar',
        data: {{
            labels: {json.dumps(labels)},
            datasets: [{{
                label: '{label}',
                data: {json.dumps(values)},
                backgroundColor: '{color}55',
                borderColor: '{color}',
                borderWidth: 1,
                borderRadius: 4,
            }}]
        }},
        options: {{
            responsive: true,
            maintainAspectRatio: false,
            plugins: {{ legend: {{ display: false }} }},
            scales: {{
                x: {{ ticks: {{ color: '#888', font: {{ size: 10 }} }}, grid: {{ display: false }} }},
                y: {{ ticks: {{ color: '#888', font: {{ size: 10 }} }}, grid: {{ color: '#2a2a2a' }}, beginAtZero: true }}
            }}
        }}
    }});"""


def _card(slug: str, records: list, channel: dict) -> tuple:
    color = GAME_COLORS.get(slug, "#888")
    name  = _game_name(slug, records)

    longs  = [r for r in records if r["type"] == "long"  and r.get("stats", {}).get("views") is not None]
    shorts = [r for r in records if r["type"] == "short" and r.get("stats", {}).get("views") is not None]

    total_views = sum(r["stats"]["views"] for r in longs + shorts)
    avg_long    = int(sum(r["stats"]["views"] for r in longs)  / len(longs))  if longs  else 0
    avg_short   = int(sum(r["stats"]["views"] for r in shorts) / len(shorts)) if shorts else 0
    best        = max(longs + shorts, key=lambda r: r["stats"]["views"], default=None)
    subscribers = channel.get("subscribers", 0)

    # Graphique compilations
    longs_sorted = sorted([r for r in longs if r.get("published_at")], key=lambda r: r["published_at"])
    long_labels  = [f"#{r['episode']}" if r.get("episode") else r["published_at"] for r in longs_sorted]
    long_values  = [r["stats"]["views"] for r in longs_sorted]

    # Graphique shorts
    shorts_sorted = sorted([r for r in shorts if r.get("published_at")], key=lambda r: r["published_at"])
    short_labels  = [f"#{r['episode']}" if r.get("episode") else r["published_at"] for r in shorts_sorted]
    short_values  = [r["stats"]["views"] for r in shorts_sorted]

    cid_long  = f"chart_long_{slug.replace('-', '_')}"
    cid_short = f"chart_short_{slug.replace('-', '_')}"

    charts_js = ""
    if long_labels:
        charts_js += _chart_js(cid_long, long_labels, long_values, color, "Vues")
    if short_labels:
        charts_js += _chart_js(cid_short, short_labels, short_values, color, "Vues")

    long_chart_html  = f'<div class="chart-wrap"><canvas id="{cid_long}"></canvas></div>' if long_labels else '<p class="no-data">Pas encore de données</p>'
    short_chart_html = f'<div class="chart-wrap"><canvas id="{cid_short}"></canvas></div>' if short_labels else '<p class="no-data">Pas encore de données</p>'

    best_html = ""
    if best:
        best_html = f'<div class="best">🏆 <span>{best["title"][:55]}</span> — {_fmt(best["stats"]["views"])} vues</div>'

    subs_html = f'<div class="subs" style="color:{color}">{_fmt(subscribers)} <span>abonnés</span></div>' if subscribers else ""

    html = f"""
    <div class="card" style="border-top: 3px solid {color}">
        <div class="card-header">
            <h2 style="color:{color}">{name}</h2>
            {subs_html}
        </div>
        <div class="stats-row">
            <div class="stat"><div class="val">{_fmt(total_views)}</div><div class="lbl">vues totales</div></div>
            <div class="stat"><div class="val">{len(longs)}</div><div class="lbl">compilations</div></div>
            <div class="stat"><div class="val">{_fmt(avg_long)}</div><div class="lbl">moy./compil</div></div>
            <div class="stat"><div class="val">{len(shorts)}</div><div class="lbl">shorts</div></div>
            <div class="stat"><div class="val">{_fmt(avg_short)}</div><div class="lbl">moy./short</div></div>
        </div>
        {best_html}
        <div class="charts-row">
            <div class="chart-block">
                <div class="chart-label">Compilations</div>
                {long_chart_html}
            </div>
            <div class="chart-block">
                <div class="chart-label">Shorts</div>
                {short_chart_html}
            </div>
        </div>
    </div>
    """
    return html, charts_js


def generate() -> None:
    os.makedirs("docs", exist_ok=True)
    all_data   = _load_all()
    channels   = _load_channels()
    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    total_views_all = sum(
        r["stats"]["views"]
        for records in all_data.values()
        for r in records
        if r.get("stats", {}).get("views") is not None
    )
    total_videos  = sum(len(r) for r in all_data.values())
    total_subs    = sum(c.get("subscribers", 0) for c in channels.values())

    cards_html = ""
    charts_js  = ""
    for slug, records in all_data.items():
        card_html, chart_js = _card(slug, records, channels.get(slug, {}))
        cards_html += card_html
        charts_js  += chart_js

    if not cards_html:
        cards_html = '<p class="no-data" style="text-align:center;margin-top:60px">Aucune donnée — lance bootstrap_analytics.py</p>'

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; padding: 24px; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .meta {{ color: #555; font-size: .8rem; margin-bottom: 28px; }}
  .summary {{ display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }}
  .summary-stat {{ background: #1a1a1a; border-radius: 10px; padding: 14px 22px; flex: 1; min-width: 130px; }}
  .summary-stat .val {{ font-size: 1.8rem; font-weight: 700; }}
  .summary-stat .lbl {{ color: #666; font-size: .75rem; margin-top: 3px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(520px, 1fr)); gap: 18px; }}
  .card {{ background: #1a1a1a; border-radius: 12px; padding: 18px; }}
  .card-header {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 14px; }}
  .card-header h2 {{ font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; }}
  .subs {{ font-size: 1.1rem; font-weight: 700; }}
  .subs span {{ font-size: .7rem; font-weight: 400; color: #888; }}
  .stats-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
  .stat {{ background: #242424; border-radius: 8px; padding: 7px 11px; flex: 1; min-width: 70px; }}
  .stat .val {{ font-size: 1rem; font-weight: 700; }}
  .stat .lbl {{ color: #666; font-size: .65rem; margin-top: 2px; }}
  .best {{ background: #242424; border-radius: 8px; padding: 7px 11px; font-size: .8rem;
           color: #888; margin-bottom: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .best span {{ color: #ddd; }}
  .charts-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  .chart-block {{ background: #161616; border-radius: 8px; padding: 10px; }}
  .chart-label {{ font-size: .7rem; color: #666; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }}
  .chart-wrap {{ position: relative; height: 110px; }}
  .no-data {{ color: #444; font-size: .8rem; padding: 16px 0; text-align: center; }}
</style>
</head>
<body>
<h1>📊 Pipeline Analytics</h1>
<p class="meta">Mis à jour le {updated_at}</p>
<div class="summary">
  <div class="summary-stat"><div class="val">{_fmt(total_subs)}</div><div class="lbl">abonnés (total)</div></div>
  <div class="summary-stat"><div class="val">{_fmt(total_views_all)}</div><div class="lbl">vues totales</div></div>
  <div class="summary-stat"><div class="val">{total_videos}</div><div class="lbl">vidéos trackées</div></div>
  <div class="summary-stat"><div class="val">{len(all_data)}</div><div class="lbl">jeux actifs</div></div>
</div>
<div class="grid">
{cards_html}
</div>
<script>
window.addEventListener('load', function() {{
{charts_js}
}});
</script>
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard → {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()

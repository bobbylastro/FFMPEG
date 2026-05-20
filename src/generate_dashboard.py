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
        if not fname.endswith(".json"):
            continue
        slug = fname[:-5]
        with open(os.path.join(ANALYTICS_DIR, fname)) as f:
            records = json.load(f)
        if records:
            data[slug] = records
    return data


def _game_name(slug: str, records: list) -> str:
    for r in records:
        if r.get("game"):
            return r["game"]
    return slug.replace("-", " ").title()


def _card(slug: str, records: list) -> str:
    color    = GAME_COLORS.get(slug, "#888")
    name     = _game_name(slug, records)
    longs    = [r for r in records if r["type"] == "long"  and r.get("stats", {}).get("views") is not None]
    shorts   = [r for r in records if r["type"] == "short" and r.get("stats", {}).get("views") is not None]
    all_stat = longs + shorts

    total_views = sum(r["stats"]["views"] for r in all_stat)
    best        = max(all_stat, key=lambda r: r["stats"]["views"], default=None)
    avg_long    = int(sum(r["stats"]["views"] for r in longs)  / len(longs))  if longs  else 0
    avg_short   = int(sum(r["stats"]["views"] for r in shorts) / len(shorts)) if shorts else 0

    # Données pour le graphique (compilations triées par épisode/date)
    chart_data = sorted(
        [r for r in longs if r.get("published_at")],
        key=lambda r: r.get("published_at", ""),
    )
    labels = [f"#{r['episode']}" if r.get("episode") else r["published_at"] for r in chart_data]
    values = [r["stats"]["views"] for r in chart_data]

    chart_id = f"chart_{slug.replace('-', '_')}"
    chart_js  = ""
    if labels:
        labels_json = json.dumps(labels)
        values_json = json.dumps(values)
        chart_js = f"""
        new Chart(document.getElementById('{chart_id}'), {{
            type: 'line',
            data: {{
                labels: {labels_json},
                datasets: [{{
                    label: 'Vues',
                    data: {values_json},
                    borderColor: '{color}',
                    backgroundColor: '{color}22',
                    tension: 0.3,
                    fill: true,
                    pointBackgroundColor: '{color}',
                }}]
            }},
            options: {{
                responsive: true,
                plugins: {{ legend: {{ display: false }} }},
                scales: {{
                    x: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#333' }} }},
                    y: {{ ticks: {{ color: '#aaa' }}, grid: {{ color: '#333' }}, beginAtZero: true }}
                }}
            }}
        }});"""

    best_html = ""
    if best:
        best_html = f'<div class="best">🏆 <span>{best["title"][:50]}</span> — {best["stats"]["views"]:,} vues</div>'

    chart_html = f'<canvas id="{chart_id}" height="120"></canvas>' if labels else '<p class="no-data">Pas encore de données</p>'

    return f"""
    <div class="card" style="border-top: 3px solid {color}">
        <h2 style="color:{color}">{name}</h2>
        <div class="stats-row">
            <div class="stat"><div class="val">{total_views:,}</div><div class="lbl">vues totales</div></div>
            <div class="stat"><div class="val">{len(longs)}</div><div class="lbl">compilations</div></div>
            <div class="stat"><div class="val">{avg_long:,}</div><div class="lbl">moy. vues/compil</div></div>
            <div class="stat"><div class="val">{len(shorts)}</div><div class="lbl">shorts</div></div>
            <div class="stat"><div class="val">{avg_short:,}</div><div class="lbl">moy. vues/short</div></div>
        </div>
        {best_html}
        {chart_html}
    </div>
    """, chart_js


def generate() -> None:
    os.makedirs("docs", exist_ok=True)
    all_data   = _load_all()
    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    total_views_all = sum(
        r["stats"]["views"]
        for records in all_data.values()
        for r in records
        if r.get("stats", {}).get("views") is not None
    )
    total_videos = sum(len(r) for r in all_data.values())

    cards_html = ""
    charts_js  = ""
    for slug, records in all_data.items():
        card_html, chart_js = _card(slug, records)
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
  .meta {{ color: #666; font-size: .85rem; margin-bottom: 32px; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 32px; flex-wrap: wrap; }}
  .summary-stat {{ background: #1a1a1a; border-radius: 10px; padding: 16px 24px; flex: 1; min-width: 140px; }}
  .summary-stat .val {{ font-size: 1.8rem; font-weight: 700; }}
  .summary-stat .lbl {{ color: #888; font-size: .8rem; margin-top: 2px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 20px; }}
  .card {{ background: #1a1a1a; border-radius: 12px; padding: 20px; }}
  .card h2 {{ font-size: 1.1rem; margin-bottom: 14px; text-transform: uppercase; letter-spacing: 1px; }}
  .stats-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }}
  .stat {{ background: #242424; border-radius: 8px; padding: 8px 12px; flex: 1; min-width: 80px; }}
  .stat .val {{ font-size: 1.1rem; font-weight: 700; }}
  .stat .lbl {{ color: #777; font-size: .7rem; margin-top: 2px; }}
  .best {{ background: #242424; border-radius: 8px; padding: 8px 12px; font-size: .82rem;
           color: #aaa; margin-bottom: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .best span {{ color: #e0e0e0; }}
  .no-data {{ color: #555; font-size: .9rem; padding: 20px 0; text-align: center; }}
</style>
</head>
<body>
<h1>📊 Pipeline Analytics</h1>
<p class="meta">Mis à jour le {updated_at}</p>
<div class="summary">
  <div class="summary-stat"><div class="val">{total_views_all:,}</div><div class="lbl">vues totales</div></div>
  <div class="summary-stat"><div class="val">{total_videos}</div><div class="lbl">vidéos trackées</div></div>
  <div class="summary-stat"><div class="val">{len(all_data)}</div><div class="lbl">jeux actifs</div></div>
</div>
<div class="grid">
{cards_html}
</div>
<script>
{charts_js}
</script>
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard → {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()

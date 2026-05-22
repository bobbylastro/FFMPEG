"""Génère docs/index.html — dashboard analytics GitHub Pages."""
import json
import os
from datetime import datetime

ANALYTICS_DIR = "data/analytics"
OUTPUT_PATH   = "docs/index.html"

GAME_COLORS = {
    "valorant":          "#FF3B30",  # rouge vif
    "apex-legends":      "#FF9F0A",  # orange/ambre
    "marvel-rivals":     "#E8001C",  # rouge Marvel
    "the-finals":        "#F0A500",  # or The Finals
    "rocket-league":     "#0A84FF",  # bleu vif
    "r6-siege":          "#BF5AF2",  # violet
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


def _build_chart_data(all_data: dict, video_type: str) -> dict:
    """Construit un objet Chart.js multi-datasets (une ligne par jeu)."""
    game_date_views = {}  # slug -> {date: views}
    all_dates = set()

    for slug, records in all_data.items():
        filtered = [
            r for r in records
            if r["type"] == video_type
            and r.get("stats", {}).get("views") is not None
            and r.get("published_at")
        ]
        if not filtered:
            continue
        date_views: dict[str, int] = {}
        for r in filtered:
            date = r["published_at"][:10]
            date_views[date] = date_views.get(date, 0) + r["stats"]["views"]
            all_dates.add(date)
        game_date_views[slug] = date_views

    sorted_dates = sorted(all_dates)

    datasets = []
    for slug, date_views in game_date_views.items():
        color = GAME_COLORS.get(slug, "#888")
        name  = _game_name(slug, all_data[slug])
        values = [date_views.get(d) for d in sorted_dates]  # None = pas de donnée
        datasets.append({
            "label":               name,
            "data":                values,
            "borderColor":         color,
            "backgroundColor":     color + "22",
            "borderWidth":         2.5,
            "pointBackgroundColor": color,
            "pointRadius":         4,
            "pointHoverRadius":    7,
            "tension":             0.3,
            "fill":                False,
            "spanGaps":            True,
        })

    return {"labels": sorted_dates, "datasets": datasets}


def generate() -> None:
    os.makedirs("docs", exist_ok=True)
    all_data   = _load_all()
    channels   = _load_channels()
    updated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    shorts_data = _build_chart_data(all_data, "short")
    longs_data  = _build_chart_data(all_data, "long")

    # Légende
    legend_items = []
    for slug, records in all_data.items():
        color = GAME_COLORS.get(slug, "#888")
        name  = _game_name(slug, records)
        legend_items.append(
            f'<div class="legend-item">'
            f'<div class="legend-dot" style="background:{color}"></div>'
            f'<span>{name}</span>'
            f'</div>'
        )
    legend_html = "\n  ".join(legend_items)

    # Cartes abonnés
    subs_cards = []
    for slug, records in all_data.items():
        color = GAME_COLORS.get(slug, "#888")
        name  = _game_name(slug, records)
        ch    = channels.get(slug, {})
        subs  = ch.get("subscribers", 0)
        val   = _fmt(subs) if subs else "—"
        subs_cards.append(
            f'<div class="subs-card" style="border-top-color:{color}">'
            f'<div class="game-name" style="color:{color}">{name}</div>'
            f'<div class="subs-val">{val}</div>'
            f'<div class="subs-lbl">abonnés</div>'
            f'</div>'
        )
    subs_html = "\n  ".join(subs_cards)

    no_data_msg = ""
    if not all_data:
        no_data_msg = '<p class="no-data">Aucune donnée — lance bootstrap_analytics.py</p>'

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Analytics</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ height: 100%; }}
  body {{ background: #0f0f0f; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; min-height: 100vh; display: flex; flex-direction: column; }}

  header {{ padding: 20px 28px 14px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }}
  h1 {{ font-size: 1.3rem; font-weight: 700; }}
  .meta {{ color: #444; font-size: .75rem; margin-top: 3px; }}

  .toggle {{ background: #1a1a1a; border-radius: 8px; display: flex; padding: 3px; gap: 3px; }}
  .toggle button {{ background: transparent; border: none; color: #666; font-size: .85rem; padding: 6px 18px; border-radius: 6px; cursor: pointer; transition: all .15s; font-family: inherit; }}
  .toggle button.active {{ background: #2a2a2a; color: #e0e0e0; }}

  .chart-section {{ flex: 1; padding: 0 24px 10px; display: flex; flex-direction: column; min-height: 0; }}
  .chart-container {{ flex: 1; background: #1a1a1a; border-radius: 14px; padding: 20px; position: relative; min-height: 380px; }}

  .legend {{ display: flex; flex-wrap: wrap; gap: 10px 20px; padding: 14px 28px; flex-shrink: 0; }}
  .legend-item {{ display: flex; align-items: center; gap: 8px; font-size: .85rem; color: #aaa; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}

  .subs-row {{ display: flex; gap: 10px; padding: 4px 24px 24px; flex-wrap: wrap; flex-shrink: 0; }}
  .subs-card {{ background: #1a1a1a; border-radius: 10px; padding: 12px 16px; flex: 1; min-width: 110px; border-top: 3px solid; }}
  .game-name {{ font-size: .65rem; text-transform: uppercase; letter-spacing: .8px; margin-bottom: 6px; }}
  .subs-val {{ font-size: 1.6rem; font-weight: 700; }}
  .subs-lbl {{ font-size: .65rem; color: #555; margin-top: 2px; }}

  .no-data {{ color: #444; font-size: .9rem; text-align: center; padding: 60px; }}
</style>
</head>
<body>

<header>
  <div>
    <h1>Pipeline Analytics</h1>
    <p class="meta">Mis à jour le {updated_at}</p>
  </div>
  <div class="toggle">
    <button id="btn-shorts" class="active" onclick="switchMode('shorts')">Shorts</button>
    <button id="btn-longs" onclick="switchMode('longs')">Vidéos</button>
  </div>
</header>

<div class="chart-section">
  <div class="chart-container">
    {no_data_msg}
    <canvas id="mainChart"></canvas>
  </div>
</div>

<div class="legend">
  {legend_html}
</div>

<div class="subs-row">
  {subs_html}
</div>

<script>
const shortsData = {json.dumps(shorts_data, ensure_ascii=False)};
const longsData  = {json.dumps(longs_data,  ensure_ascii=False)};

let currentChart = null;

function buildChart(data) {{
  if (currentChart) currentChart.destroy();
  const ctx = document.getElementById('mainChart').getContext('2d');
  currentChart = new Chart(ctx, {{
    type: 'line',
    data: data,
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'nearest', intersect: false }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          backgroundColor: '#1c1c1c',
          borderColor: '#333',
          borderWidth: 1,
          titleColor: '#888',
          bodyColor: '#e0e0e0',
          padding: 12,
          boxPadding: 6,
          callbacks: {{
            title: (items) => items[0]?.label || '',
            label: (item) => {{
              const v = item.parsed.y;
              if (v === null || v === undefined) return null;
              return '  ' + item.dataset.label + '  —  ' + v.toLocaleString('fr-FR') + ' vues';
            }},
            filter: (item) => item.parsed.y !== null && item.parsed.y !== undefined,
          }},
        }},
      }},
      scales: {{
        x: {{
          ticks: {{ color: '#555', font: {{ size: 11 }} }},
          grid: {{ color: '#1e1e1e' }},
        }},
        y: {{
          ticks: {{ color: '#555', font: {{ size: 11 }} }},
          grid: {{ color: '#1e1e1e' }},
          beginAtZero: true,
        }},
      }},
    }},
  }});
}}

function switchMode(mode) {{
  document.getElementById('btn-shorts').classList.toggle('active', mode === 'shorts');
  document.getElementById('btn-longs').classList.toggle('active', mode === 'longs');
  buildChart(mode === 'shorts' ? shortsData : longsData);
}}

window.addEventListener('load', () => buildChart(shortsData));
</script>
</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dashboard → {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()

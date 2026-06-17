"""
Affiche les stats YouTube pour tous les jeux.

Usage : python show_analytics.py [--refresh]
  --refresh : re-fetch les stats depuis l'API avant d'afficher
"""
import sys
import logging

from src.fetch_clips_twitch import TWITCH_GAME_CATALOG
from src.fetch_analytics import refresh_stats, print_report

logging.basicConfig(level=logging.WARNING)

do_refresh = "--refresh" in sys.argv

for slug, name in TWITCH_GAME_CATALOG.items():
    if do_refresh:
        print(f"Fetching stats for {name}...")
        refresh_stats(slug)
    print_report(slug, name)

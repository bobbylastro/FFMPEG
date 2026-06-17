"""
Rafraîchit les stats YouTube (vues + abonnés) pour tous les jeux
et régénère le dashboard GitHub Pages.

Usage : python refresh_analytics.py
"""
import logging

from src.fetch_clips_twitch import TWITCH_GAME_CATALOG
from src.fetch_analytics import refresh_stats, refresh_channel_stats, print_report
from src.generate_dashboard import generate as generate_dashboard

logging.basicConfig(level=logging.WARNING)

for slug, name in TWITCH_GAME_CATALOG.items():
    refresh_stats(slug)
    refresh_channel_stats(slug)
    print_report(slug, name)

generate_dashboard()
print("Dashboard régénéré.")

"""
Vérifie que tous les tokens YouTube sont valides sans rien uploader.

Usage : python check_tokens.py
"""
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GAMES = {
    "r6-siege": "YOUTUBE_TOKEN_R6_SIEGE",
}

ok = True
for game, env_key in GAMES.items():
    raw = os.getenv(env_key)
    if not raw:
        print(f"  ⚠️  {game:<16} — secret {env_key} manquant")
        ok = False
        continue
    try:
        data = json.loads(raw)
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=data["scopes"],
        )
        if not creds.valid:
            creds.refresh(Request())
        yt = build("youtube", "v3", credentials=creds)
        res = yt.channels().list(part="snippet", mine=True).execute()
        channel = res["items"][0]["snippet"]["title"] if res.get("items") else "???"
        print(f"  ✅  {game:<16} — {channel}  [{data['client_id'][:30]}...]")
    except Exception as e:
        print(f"  ❌  {game:<16} — {e}")
        ok = False

sys.exit(0 if ok else 1)

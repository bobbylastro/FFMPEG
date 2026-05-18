"""
Script one-shot à lancer UNE SEULE FOIS en local pour générer le token OAuth YouTube.

Usage :
    1. Télécharge client_secrets.json depuis Google Cloud Console
       (APIs & Services → Credentials → OAuth 2.0 Client ID → type Desktop)
    2. Place-le à la racine du projet
    3. Lance : python auth_youtube.py
    4. Ouvre l'URL affichée dans ton navigateur, accepte, copie le code
    5. Colle le code dans le terminal
    6. Le fichier token.json est généré
    7. Copie son contenu dans le secret GitHub YOUTUBE_TOKEN
"""
import json
from google_auth_oauthlib.flow import Flow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = Flow.from_client_secrets_file(
    "client_secrets.json",
    scopes=SCOPES,
    redirect_uri="urn:ietf:wg:oauth:2.0:oob",
)

auth_url, _ = flow.authorization_url(prompt="consent")
print("\n👉 Ouvre cette URL dans ton navigateur :\n")
print(auth_url)
print()

code = input("Colle ici le code affiché par Google : ").strip()
flow.fetch_token(code=code)
creds = flow.credentials

token_data = {
    "token":         creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri":     creds.token_uri,
    "client_id":     creds.client_id,
    "client_secret": creds.client_secret,
    "scopes":        list(creds.scopes),
}
with open("token.json", "w") as f:
    json.dump(token_data, f, indent=2)

print("\n✅ token.json généré.")
print("   → Copie son contenu dans le secret GitHub YOUTUBE_TOKEN\n")
print(json.dumps(token_data, indent=2))

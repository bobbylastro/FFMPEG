"""
Script one-shot à lancer UNE SEULE FOIS en local pour générer le token OAuth YouTube.

Usage :
    1. Télécharge client_secrets.json depuis Google Cloud Console
       (APIs & Services → Credentials → OAuth 2.0 Client ID → type Desktop)
    2. Place-le à la racine du projet
    3. Lance : python auth_youtube.py [--secrets client_secrets.json] [--out token.json]
    4. Ouvre l'URL affichée dans ton navigateur, accepte, copie le code
    5. Colle le code dans le terminal
    6. Le fichier token.json est généré
    7. Copie son contenu dans le secret GitHub YOUTUBE_TOKEN_<GAME>

Pour un 2ème projet GCP :
    python auth_youtube.py --secrets client_secrets_p2.json --out token_apex.json
"""
import argparse
import json
from google_auth_oauthlib.flow import Flow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

parser = argparse.ArgumentParser()
parser.add_argument("--secrets", default="client_secrets.json", help="Fichier client_secrets à utiliser")
parser.add_argument("--out", default="token.json", help="Fichier de sortie du token")
args = parser.parse_args()

flow = Flow.from_client_secrets_file(
    args.secrets,
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
with open(args.out, "w") as f:
    json.dump(token_data, f, indent=2)

print(f"\n✅ {args.out} généré.")
print(f"   → Copie son contenu dans le secret GitHub YOUTUBE_TOKEN_<GAME>\n")
print(json.dumps(token_data, indent=2))

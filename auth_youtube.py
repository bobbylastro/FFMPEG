"""
Script one-shot à lancer UNE SEULE FOIS en local pour générer le token OAuth YouTube.

Usage :
    1. Lance : python auth_youtube.py [--secrets client_secrets.json] [--out token.json]
    2. Ouvre l'URL affichée dans ton navigateur
    3. Connecte-toi avec l'email de la chaîne YouTube concernée
    4. Accepte les permissions (ignore l'avertissement "app non vérifiée")
    5. Google redirige vers localhost → la page ne charge pas, c'est normal
    6. Copie l'URL complète depuis la barre d'adresse et colle-la dans le terminal
    7. Le fichier token est généré — copie son contenu dans le secret GitHub YOUTUBE_TOKEN_<GAME>

Pour un 2ème projet GCP :
    python auth_youtube.py --secrets client_secrets_p2.json --out token_apex.json
"""
import argparse
import json
import os
from google_auth_oauthlib.flow import Flow

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

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
    redirect_uri="http://localhost",
)

auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
print("\n👉 Ouvre cette URL dans ton navigateur :\n")
print(auth_url)
print()
print("Après avoir accepté, Google redirige vers localhost → la page ne charge pas, c'est normal.")
print("Copie l'URL COMPLÈTE depuis ta barre d'adresse (http://localhost/?code=...) et colle-la ici :")
print()

redirect_response = input("URL complète : ").strip()
flow.fetch_token(authorization_response=redirect_response)
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

"""
Post-compilation notifier for URKL robot fight compilations.
After a compilation is done in validate_server.py:
  1. Generates a varied TikTok EN caption via Claude
  2. Uploads the video to R2
  3. Triggers urkl_notify.yml GitHub workflow to send the email

Usage (standalone test):
  python3 src/urkl_notifier.py /path/to/compilation.mp4 5
"""
import os
import sys
import json
import random
import subprocess
import boto3
from datetime import datetime, timezone
from botocore.config import Config
from dotenv import load_dotenv
import anthropic

load_dotenv("/workspaces/FFMPEG/.env")

R2_ENDPOINT   = os.getenv("R2_ENDPOINT", "https://04b6deea0b051f8adfb8273b37d9861f.r2.cloudflarestorage.com")
R2_BUCKET     = os.getenv("R2_BUCKET", "clips")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_PUBLIC_BASE = "https://clips.ultimate-playground.com"
LAST_R2_STATE  = "/workspaces/FFMPEG/data/urkl_last_r2.json"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Different caption angles to ensure variety across compilations
CAPTION_ANGLES = [
    "pure adrenaline — focus on the jaw-dropping speed and violence of the hits",
    "crowd/fan reaction — emphasise the insane crowd energy and hype moments",
    "technical mastery — highlight the skill and precision of the robot controllers",
    "underdog story — the tension, the comeback, the unexpected moments",
    "cinematic — short, dramatic, almost poetic; makes the viewer feel the impact",
    "hype/call-to-action — get the viewer to share or tag a friend",
]

HASHTAG_SETS = [
    "#robotcombat #urkl #battlebot",
    "#robotfight #urkl #combatrobots",
    "#urkl #robotwars #fighting",
    "#robotcombat #urkl #robots",
    "#battlebot #urkl #robotfight",
    "#urkl #epicfights #robots",
]


def generate_caption(clip_count: int) -> str:
    """Generate a varied TikTok EN caption for a URKL robot fight compilation."""
    if not ANTHROPIC_API_KEY:
        return f"🤖 TOP {clip_count} ROBOT FIGHT MOMENTS 🔥 Pure steel & sparks\n#robotcombat #urkl #battlebot"

    angle = random.choice(CAPTION_ANGLES)
    hashtags = random.choice(HASHTAG_SETS)

    prompt = f"""You write TikTok captions for robot combat highlight compilations (URKL league).
The video contains the top {clip_count} best action moments from a live robot fight event.

Today's angle: {angle}

Write a TikTok caption:
- Full English only
- 1-2 short punchy sentences (max ~150 chars total before hashtags)
- Tone: exciting, raw, no corporate speak
- End with EXACTLY these hashtags on a new line: {hashtags}
- No emoji in the caption text itself (emojis ok in hashtag line if needed)
- Do NOT mention "compilation", "top {clip_count}", or numbers — be evocative, not descriptive

Output ONLY the caption text, nothing else."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _r2_client():
    if not R2_ACCESS_KEY or not R2_SECRET_KEY:
        raise RuntimeError("R2_ACCESS_KEY or R2_SECRET_KEY not set")
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _delete_previous_r2(client) -> None:
    """Delete the previous URKL compilation (video + player page) from R2 if exists."""
    if not os.path.exists(LAST_R2_STATE):
        return
    try:
        with open(LAST_R2_STATE) as f:
            state = json.load(f)
        for key_field in ("r2_key", "player_key"):
            old_key = state.get(key_field)
            if old_key:
                client.delete_object(Bucket=R2_BUCKET, Key=old_key)
                print(f"[urkl_notifier] Supprimé du R2: {old_key}")
    except Exception as e:
        print(f"[urkl_notifier] Suppression R2 échouée (ignorée): {e}")


def _make_player_html(video_url: str, clip_count: int) -> str:
    """Page HTML pour sauvegarder la compilation dans Photos sur iPhone."""
    import json as _json
    v = _json.dumps(video_url)
    title = _json.dumps(f"URKL — {clip_count} clips")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>URKL Compilation</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;background:#0a0a0a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;padding:24px;min-height:100vh}}
video{{width:100%;max-width:480px;max-height:60vh;border-radius:12px;background:#111}}
.title{{font-size:14px;font-weight:600;text-align:center;opacity:.6}}
.btn{{width:100%;max-width:400px;background:#f59e0b;color:#000;border:none;border-radius:14px;padding:18px;font-size:17px;font-weight:700;cursor:pointer}}
.btn:disabled{{opacity:.5}}
.hint{{font-size:12px;color:#555;text-align:center;max-width:300px;line-height:1.5}}
</style>
</head>
<body>
<video id="v" playsinline controls preload="auto"></video>
<p class="title">🤖 URKL Robot Fight Compilation</p>
<button class="btn" id="btn" disabled>Chargement…</button>
<p class="hint" id="hint">Si ça ne marche pas : appuie longuement sur la vidéo → "Enregistrer dans Photos"</p>
<script>
const videoUrl={v},videoTitle={title};
const btn=document.getElementById('btn'),hint=document.getElementById('hint');
document.getElementById('v').src=videoUrl;
let readyBlob=null;
fetch(videoUrl).then(r=>r.blob()).then(b=>{{
  readyBlob=b;
  btn.disabled=false;btn.textContent='⬇ Enregistrer dans Photos';
}}).catch(()=>{{
  btn.disabled=false;btn.textContent='⬇ Enregistrer dans Photos';
  hint.textContent='Appuie longuement sur la vidéo → "Enregistrer dans Photos"';
}});
btn.onclick=function(){{
  if(!readyBlob){{hint.textContent='Encore en chargement…';return;}}
  const file=new File([readyBlob],'urkl_compilation.mp4',{{type:'video/mp4'}});
  if(navigator.share&&navigator.canShare&&navigator.canShare({{files:[file]}})){{
    navigator.share({{files:[file],title:videoTitle}}).catch(()=>{{
      hint.textContent='Appuie longuement sur la vidéo → "Enregistrer dans Photos"';
    }});
  }}else{{
    const a=document.createElement('a');
    a.href=URL.createObjectURL(readyBlob);
    a.download='urkl_compilation.mp4';
    document.body.appendChild(a);a.click();
    setTimeout(()=>{{URL.revokeObjectURL(a.href);document.body.removeChild(a)}},1000);
  }}
}};
</script>
</body>
</html>"""


def upload_to_r2(video_path: str, clip_count: int) -> tuple[str, str]:
    """Upload video + player page to R2, delete previous. Returns (video_url, player_url)."""
    client = _r2_client()
    _delete_previous_r2(client)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    r2_key      = f"urkl/compilation_{ts}.mp4"
    player_key  = f"urkl/player_{ts}.html"

    client.upload_file(
        video_path, R2_BUCKET, r2_key,
        ExtraArgs={"ContentType": "video/mp4"},
    )

    video_url  = f"{R2_PUBLIC_BASE}/{r2_key}"
    player_html = _make_player_html(video_url, clip_count)
    client.put_object(
        Bucket=R2_BUCKET, Key=player_key,
        Body=player_html.encode(), ContentType="text/html; charset=utf-8",
    )
    player_url = f"{R2_PUBLIC_BASE}/{player_key}"

    os.makedirs(os.path.dirname(LAST_R2_STATE), exist_ok=True)
    with open(LAST_R2_STATE, "w") as f:
        json.dump({
            "r2_key": r2_key,
            "player_key": player_key,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }, f)

    return video_url, player_url


def trigger_email_workflow(video_url: str, caption: str, clip_count: int) -> bool:
    """Trigger the urkl_notify GitHub Actions workflow to send the email."""
    env = os.environ.copy()
    if os.getenv("GH_TOKEN"):
        env["GH_TOKEN"] = os.getenv("GH_TOKEN")
    result = subprocess.run(
        [
            "gh", "workflow", "run", "urkl_notify.yml",
            "-f", f"video_url={video_url}",
            "-f", f"caption={caption}",
            "-f", f"clip_count={clip_count}",
        ],
        capture_output=True,
        text=True,
        cwd="/workspaces/FFMPEG",
        env=env,
    )
    if result.returncode != 0:
        print(f"[urkl_notifier] gh error: {result.stderr.strip()}")
        return False
    return True


def run(video_path: str, clip_count: int) -> dict:
    """Full post-compilation notification flow. Returns result dict."""
    result = {"ok": False, "caption": "", "video_url": "", "error": ""}

    print(f"[urkl_notifier] Génération caption ({clip_count} clips)…")
    try:
        caption = generate_caption(clip_count)
        result["caption"] = caption
        print(f"[urkl_notifier] Caption: {caption[:80]}…")
    except Exception as e:
        result["error"] = f"caption: {e}"
        return result

    print(f"[urkl_notifier] Upload R2…")
    try:
        video_url, player_url = upload_to_r2(video_path, clip_count)
        result["video_url"] = video_url
        result["player_url"] = player_url
        print(f"[urkl_notifier] Vidéo : {video_url}")
        print(f"[urkl_notifier] Player: {player_url}")
    except Exception as e:
        result["error"] = f"r2: {e}"
        return result

    print(f"[urkl_notifier] Déclenchement email workflow…")
    ok = trigger_email_workflow(player_url, caption, clip_count)
    if ok:
        result["ok"] = True
        print("[urkl_notifier] Email en route via GitHub Actions ✓")
    else:
        result["error"] = "gh workflow trigger failed"

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 urkl_notifier.py /path/video.mp4 <clip_count>")
        sys.exit(1)
    r = run(sys.argv[1], int(sys.argv[2]))
    print(json.dumps(r, indent=2, ensure_ascii=False))

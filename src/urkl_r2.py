"""
R2 helpers for the URKL clip pipeline.
Clips live at: urkl-clips/clip_XX.mp4
State lives at: urkl-clips/_state.json
Moments live at: /workspaces/FFMPEG/data/urkl_moments.json  (local, repo-dir)
"""
import os, json, io
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv("/workspaces/FFMPEG/.env")

R2_ENDPOINT    = os.getenv("R2_ENDPOINT", "https://04b6deea0b051f8adfb8273b37d9861f.r2.cloudflarestorage.com")
R2_BUCKET      = os.getenv("R2_BUCKET", "clips")
R2_ACCESS_KEY  = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY  = os.getenv("R2_SECRET_KEY")
R2_PUBLIC_BASE = "https://clips.ultimate-playground.com"
CLIPS_PREFIX   = "urkl-clips"
STATE_KEY      = f"{CLIPS_PREFIX}/_state.json"


def client():
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def clip_key(fname: str) -> str:
    return f"{CLIPS_PREFIX}/{fname}"


def clip_url(fname: str) -> str:
    return f"{R2_PUBLIC_BASE}/{CLIPS_PREFIX}/{fname}"


def thumb_key(fname: str) -> str:
    return f"{CLIPS_PREFIX}/thumbs/{fname}.jpg"


def thumb_url(fname: str) -> str:
    return f"{R2_PUBLIC_BASE}/{CLIPS_PREFIX}/thumbs/{fname}.jpg"


def list_clips(r2=None) -> list[str]:
    """Return sorted list of clip filenames in R2."""
    r2 = r2 or client()
    resp = r2.list_objects_v2(Bucket=R2_BUCKET, Prefix=f"{CLIPS_PREFIX}/clip_")
    keys = [o["Key"] for o in resp.get("Contents", [])]
    return sorted(os.path.basename(k) for k in keys if k.endswith(".mp4"))


def clip_exists(fname: str, r2=None) -> bool:
    r2 = r2 or client()
    try:
        r2.head_object(Bucket=R2_BUCKET, Key=clip_key(fname))
        return True
    except Exception:
        return False


def upload_clip(local_path: str, fname: str, r2=None) -> str:
    """Upload a local clip to R2, return public URL."""
    r2 = r2 or client()
    r2.upload_file(local_path, R2_BUCKET, clip_key(fname),
                   ExtraArgs={"ContentType": "video/mp4"})
    return clip_url(fname)


def upload_thumb(local_path: str, fname: str, r2=None):
    """Upload a thumbnail to R2."""
    r2 = r2 or client()
    r2.upload_file(local_path, R2_BUCKET, thumb_key(fname),
                   ExtraArgs={"ContentType": "image/jpeg"})


def thumb_exists(fname: str, r2=None) -> bool:
    r2 = r2 or client()
    try:
        r2.head_object(Bucket=R2_BUCKET, Key=thumb_key(fname))
        return True
    except Exception:
        return False


def load_state(r2=None) -> dict:
    r2 = r2 or client()
    try:
        obj = r2.get_object(Bucket=R2_BUCKET, Key=STATE_KEY)
        return json.loads(obj["Body"].read())
    except Exception:
        return {}


def save_state(state: dict, r2=None):
    r2 = r2 or client()
    body = json.dumps(state, indent=2).encode()
    r2.put_object(Bucket=R2_BUCKET, Key=STATE_KEY,
                  Body=body, ContentType="application/json")


def download_clip(fname: str, local_path: str, r2=None):
    """Download a clip from R2 to a local path."""
    r2 = r2 or client()
    r2.download_file(R2_BUCKET, clip_key(fname), local_path)


def delete_clip(fname: str, r2=None):
    """Delete a clip (and its thumbnail if it exists) from R2."""
    r2 = r2 or client()
    try:
        r2.delete_object(Bucket=R2_BUCKET, Key=clip_key(fname))
    except Exception:
        pass
    try:
        r2.delete_object(Bucket=R2_BUCKET, Key=thumb_key(fname))
    except Exception:
        pass

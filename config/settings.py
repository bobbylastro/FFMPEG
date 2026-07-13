import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")

REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")

YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")


GAME = os.getenv("GAME", "Valorant")
_games_env = os.getenv("GAMES", "")
GAMES = [g.strip() for g in _games_env.split(",") if g.strip()] if _games_env else [GAME]
CLIPS_DAYS_AGO_START = int(os.getenv("CLIPS_DAYS_AGO_START", 3))
CLIPS_DAYS_AGO_END = int(os.getenv("CLIPS_DAYS_AGO_END", 2))
CLIPS_PER_VIDEO = int(os.getenv("CLIPS_PER_VIDEO", 20))
MAX_CLIP_DURATION = int(os.getenv("MAX_CLIP_DURATION", 60))
MIN_CLIP_DURATION = int(os.getenv("MIN_CLIP_DURATION", 20))
MIN_VELOCITY = float(os.getenv("MIN_VELOCITY", 50))
EXCLUDED_LANGUAGES = []
EXCLUDED_BROADCASTERS = [b.lower() for b in os.getenv("EXCLUDED_BROADCASTERS",
    "rocketleague,rlcs,rlesports,psyonixofficial,"
    "northernlion,sodapoppin,xqc,hasanabi,pokimane,mizkif"
).split(",")]
ACTION_KEYWORDS = [k.lower() for k in os.getenv("ACTION_KEYWORDS",
    # Spectacular goals
    "aerial,ceiling shot,ceiling goal,air dribble,redirect,double tap,musty,flip reset,pinch,backboard,long shot,"
    # Saves
    "epic save,cross-map save,last man back,"
    # Mechanics
    "freestyler,dribble,speed flip,wave dash,half flip,wall shot,reset,"
    # Clutch / ranked
    "overtime goal,0 seconds,clutch,1v3,ssl,supersonic legend,grand champ,"
    # Hype adjectives
    "insane,crazy,sick,nutty,godlike,cracked,unreal,impossible,banger,nasty,crispy,"
    # Generic highlight markers
    "outplay,highlight,goal of the day,best goal"
).split(",")]

OUTPUT_LONG = "output/long"
OUTPUT_SHORTS = "output/shorts"
LOGS_DIR = "logs"

# Cloudflare R2 — Ultimate Playground
R2_ENDPOINT   = os.getenv("R2_ENDPOINT", "https://04b6deea0b051f8adfb8273b37d9861f.r2.cloudflarestorage.com")
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY")
R2_BUCKET     = os.getenv("R2_BUCKET", "clips")

# Supabase — Ultimate Playground
SUPABASE_URL         = os.getenv("SUPABASE_URL", "https://uahfpozqfpvemigjrzwj.supabase.co")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# API d'ingest — Ultimate Playground
INGEST_API_URL = os.getenv("INGEST_API_URL", "https://ultimate-playground.com/api/clips/ingest")
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "ingest_up_2026_secret")

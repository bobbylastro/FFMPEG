#!/usr/bin/env python3
"""
Détection des moments forts URKL par transcription + analyse IA (remplace urkl_detect.py
+ urkl_filter_rounds.py) : transcrit l'audio des rounds (chinois -> anglais via Whisper)
et demande à Claude Haiku de repérer les moments de combat réel d'après les réactions
des casters, plutôt que par pic de volume brut.

Usage: python3 src/urkl_transcribe_moments.py "<rounds_spec>" [whisper_model]
  rounds_spec: plages de rounds "MM:SS-MM:SS,MM:SS-MM:SS,..." ou "HH:MM:SS-HH:MM:SS,..."
  whisper_model: tiny|base|small|medium|large (défaut: small)

Écrit directement dans data/urkl_moments.json (même format que urkl_detect.py), prêt pour
python3 src/urkl_download.py 0.
"""
import sys, os, json, subprocess, tempfile, shutil, re, struct, math

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import whisper
import anthropic
from config.settings import ANTHROPIC_API_KEY

COOKIES          = os.path.join(BASE_DIR, "data/yt_cookies.txt")
URL              = "https://www.youtube.com/watch?v=vpyO73jyx1g"
MODEL_ID         = "claude-haiku-4-5-20251001"
MOMENTS_JSON     = os.path.join(BASE_DIR, "data/urkl_moments.json")
FULL_AUDIO_CACHE = "/tmp/urkl_full_audio_cache.webm"
PRE, POST        = 7, 3      # secondes autour du timecode identifié par l'IA
TEXT_WEIGHT      = 0.6       # poids de l'intensité texte (Haiku) dans le score combiné
DB_WEIGHT        = 0.4       # poids du percentile dB (relatif au round) dans le score combiné
SCORE_THRESHOLD  = 6.0       # score combiné mini (sur 10) pour garder un moment


def parse_ts(s: str) -> int:
    parts = [int(p) for p in s.strip().split(":")]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt(s: float) -> str:
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def download_full_audio(cache_path: str = FULL_AUDIO_CACHE) -> str:
    """Télécharge l'audio complet du stream EN CONTINU (rapide) et le met en cache.

    --download-sections fait un seek dans le flux DASH de YouTube, ce qui se fait
    beaucoup plus throttle par le CDN qu'un téléchargement séquentiel complet.
    On télécharge donc une seule fois en continu, puis on découpe localement.
    """
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 1_000_000:
        print(f"  Audio complet déjà en cache ({os.path.getsize(cache_path)/1024/1024:.0f} MB), skip download")
        return cache_path

    cmd = [
        "yt-dlp", "--cookies", COOKIES, "--no-update",
        "--js-runtimes", "node", "--remote-components", "ejs:github",
        "-f", "bestaudio", "-o", cache_path, "--no-part", URL,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(cache_path):
        raise RuntimeError(f"Download audio complet échoué: {result.stderr[-500:]}")
    print(f"  Audio complet téléchargé ({os.path.getsize(cache_path)/1024/1024:.0f} MB)")
    return cache_path


def slice_round_audio(full_audio: str, start: int, end: int, tmp_dir: str, idx: int) -> str:
    """Découpe un round localement depuis l'audio complet (instantané, pas de réseau)."""
    out_path = os.path.join(tmp_dir, f"round_{idx}.webm")
    cmd = [
        "ffmpeg", "-y", "-i", full_audio,
        "-ss", str(start), "-to", str(end),
        "-c", "copy", out_path,
        "-hide_banner", "-loglevel", "error",
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"Découpage local échoué pour round {idx}")
    return out_path


def build_prompt(transcript: str) -> str:
    return f"""You are analyzing a caster transcript (translated from Chinese) of URKL, a robot combat show.

IMPORTANT — what URKL actually is: this is NOT a BattleBots-style show with wheeled robots,
saws, hammers, or flamethrowers. URKL features two HUMANOID robots striking each other —
mostly punches, and jumping or standing kicks, with occasional acrobatic strikes — scored like
a point-fighting combat sport (points for landed strikes and knockdowns). There are no onboard
weapons. These are robots, not trained human fighters: don't expect or look for grappling,
clinches, throws, or submission-style moves — the technique level is limited to striking.
Do not expect or look for sparks, fire, blades, or mechanical weapon damage either — the
"damage" here is a robot getting staggered, knocked down, or a limb/hand no longer functioning
correctly after taking strikes.

Below is a timestamped transcript of the casters' commentary during one combat round.

Your job: identify moments of ACTUAL COMBAT ACTION — direct fighting between the two robots.

TARGET (pick these):
- A robot landing a punch, a jumping or standing kick, or an acrobatic strike on the opponent
- A robot getting staggered, knocked off balance, or sent to the ground purely from the power
  of the opponent's punch or kick (this is common and important — a strike hard enough to fell
  the robot is a top-tier moment, not a self-righting issue)
- Visible damage or malfunction resulting from a strike (e.g. a hand/arm stops working
  correctly after being hit) — as a direct consequence of an exchange, not a weapon malfunction
- A KO, a robot unable to continue, or a dominant/one-sided exchange
- A dramatic turnaround DURING an active exchange (e.g. countering into offense right after
  taking damage, landing a comeback strike)
- A robot recovering from a knockdown CAUSED BY THE OPPONENT, especially if casters react with
  surprise at how fast/slow/dramatic the recovery is (e.g. beating a count) — this is a direct
  consequence of combat, unlike unprompted self-righting
- A sudden, isolated caster exclamation ("Wow!", "Oh!", short shout) even WITHOUT a fully
  described action — casters often react half a second before or instead of narrating what
  happened, and the loudest, most genuine reactions are often the SHORTEST. Don't require a
  full sentence describing the hit — the exclamation itself is the evidence something big just
  happened. Rate its intensity on how strong/urgent the reaction itself sounds (tone, emphasis,
  repetition, exclamation marks) — NOT on how much surrounding text describes the action. A
  short, sharp "WOW!" can be a 9, even with zero context around it.

NOT interesting enough — DO NOT include:
- A robot self-righting/getting up with NO preceding hit or knockdown from the opponent
- Judges, rules, scoring explanations, pre-fight setup, replays, or dead air
- Casters just narrating robot movement/positioning with no hit, clash, or reaction happening

The transcript is machine-translated from Chinese and can be garbled, fragmented, or even
self-contradictory (e.g. "didn't hit" next to "hand is broken"). Don't require perfectly clear
phrasing — infer the likely combat action from context: impact-related words, sudden score
changes, a name followed by a caster reaction. When genuinely uncertain whether something
qualifies, INCLUDE it with a lower intensity (2-3) rather than silently dropping it — the
downstream scoring will filter out the weak ones. Do not return an empty list just because the
transcript is hard to parse — if casters are reacting to the fight, something is worth flagging.

For each moment, also rate its INTENSITY from 1 to 10 based on how the casters react — NOT on
how much text surrounds it: 1-3 = routine scoring hit, casual tone, or genuinely unclear
whether a real action even happened; 4-6 = solid hit, casters mildly excited; 7-8 = big
hit/knockdown, casters clearly excited or alarmed; 9-10 = KO, major damage, or casters
extremely hyped/shouting — a sharp, loud, short exclamation belongs here just as much as a
long descriptive sentence would. Be honest and use the full range — most moments should NOT be
9-10.

Transcript:
{transcript}

Respond with ONLY a JSON array of objects, most exciting first, e.g.:
[{{"timecode": "01:23:45", "reason": "robot A lands a heavy right hook, robot B staggers back", "intensity": 8}}]

Return at most 20 moments for this round. Return [] if nothing qualifies. No explanation outside the JSON."""


def transcribe_audio(model, audio_path, start_offset):
    result = model.transcribe(audio_path, task="translate", language="zh", verbose=False)
    lines = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        if text:
            abs_start = start_offset + seg["start"]
            lines.append((abs_start, f"{fmt(abs_start)}: {text}"))
    return lines


def rms_db(chunk):
    if not chunk:
        return -99
    sq = sum(s * s for s in chunk) / len(chunk)
    return 20 * math.log10(math.sqrt(sq) / 32768) if sq > 0 else -99


def compute_db_timeline(audio_path: str, start_offset: int) -> dict:
    """Analyse RMS seconde par seconde (même méthode que urkl_detect.py),
    retourne {seconde_absolue: db_lissé}."""
    cmd = [
        "ffmpeg", "-i", audio_path, "-ar", "8000", "-ac", "1", "-f", "s16le", "-",
        "-hide_banner", "-loglevel", "error",
    ]
    raw = subprocess.run(cmd, capture_output=True).stdout
    SR = 8000
    samples = struct.unpack(f"<{len(raw)//2}h", raw)
    rms = [rms_db(samples[i*SR:(i+1)*SR]) for i in range(len(samples)//SR)]
    smoothed = [sum(rms[max(0,i-1):i+2]) / len(rms[max(0,i-1):i+2]) for i in range(len(rms))]
    return {start_offset + i: db for i, db in enumerate(smoothed)}


def local_db(db_timeline: dict, peak: int, window: int = 2) -> float:
    """dB max autour du timecode identifié par l'IA (absorbe l'imprécision du LLM)."""
    vals = [db_timeline[t] for t in range(peak - window, peak + window + 1) if t in db_timeline]
    return max(vals) if vals else -99.0


def db_percentile(db_timeline: dict, db: float) -> float:
    """Percentile du niveau sonore par rapport à TOUT le round (0-100) — relatif plutôt
    qu'absolu, pour s'adapter au bruit de fond propre à chaque round."""
    values = list(db_timeline.values())
    if not values:
        return 50.0
    below = sum(1 for v in values if v <= db)
    return 100.0 * below / len(values)


def ask_haiku(client, transcript, max_retries: int = 2):
    """Appelle Haiku ; si la réponse est vide ([]), retente (variance d'échantillonnage
    du LLM sur des transcripts ambigus/mal traduits — souvent un faux négatif)."""
    total_in = total_out = 0
    for attempt in range(max_retries + 1):
        resp = client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            messages=[{"role": "user", "content": build_prompt(transcript)}],
        )
        total_in += resp.usage.input_tokens
        total_out += resp.usage.output_tokens
        raw = resp.content[0].text.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        moments = json.loads(match.group()) if match else []
        if moments:
            return moments, total_in, total_out
        if attempt < max_retries:
            print(f"    (0 moment renvoyé par Haiku, retry {attempt+1}/{max_retries}...)", flush=True)
    return moments, total_in, total_out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    windows = []
    for r in sys.argv[1].split(","):
        s, e = r.strip().split("-")
        windows.append((parse_ts(s), parse_ts(e)))

    whisper_model_name = sys.argv[2] if len(sys.argv) > 2 else "small"
    total_min = sum(e - s for s, e in windows) / 60
    print(f"Rounds: {len(windows)}, total {total_min:.1f} min")

    print(f"Chargement du modèle Whisper '{whisper_model_name}'...")
    model = whisper.load_model(whisper_model_name)

    print("\nTéléchargement de l'audio complet du stream (une seule fois)...", flush=True)
    full_audio = download_full_audio()

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write("\n## URKL — moments détectés par round\n\n")
            f.write("| Round | Plage | Segments | Proposés | Gardés |\n")
            f.write("|---|---|---|---|---|\n")

    tmp_dir = tempfile.mkdtemp(prefix="urkl_transcribe_")
    all_moments = []
    total_in = total_out = 0
    total_kept = total_rejected = 0
    try:
        for idx, (start, end) in enumerate(windows):
            print(f"\n[Round {idx+1}/{len(windows)}] {fmt(start)} -> {fmt(end)}")
            audio_path = slice_round_audio(full_audio, start, end, tmp_dir, idx)

            print("  Transcription...", flush=True)
            lines = transcribe_audio(model, audio_path, start)
            print(f"  {len(lines)} segments transcrits")

            print("  Analyse RMS/dB...", flush=True)
            db_timeline = compute_db_timeline(audio_path, start)

            if not lines:
                if step_summary:
                    with open(step_summary, "a") as f:
                        f.write(f"| {idx+1}/{len(windows)} | {fmt(start)}-{fmt(end)} | 0 | 0 | 0 |\n")
                continue

            lines.sort(key=lambda x: x[0])
            transcript = "\n".join(line for _, line in lines)

            print("  Analyse Haiku...", flush=True)
            round_moments, in_tok, out_tok = ask_haiku(client, transcript)
            total_in += in_tok
            total_out += out_tok

            scored = []
            for m in round_moments:
                try:
                    peak = parse_ts(m["timecode"])
                except Exception:
                    continue
                db = local_db(db_timeline, peak)
                pct = db_percentile(db_timeline, db)
                intensity = float(m.get("intensity", 5))
                score = TEXT_WEIGHT * intensity + DB_WEIGHT * (pct / 10)
                scored.append((score, peak, db, pct, intensity, m.get("reason", "")))

            scored.sort(key=lambda x: -x[0])
            print(f"  {len(scored)} moments proposés (score = {TEXT_WEIGHT}*intensité + {DB_WEIGHT}*percentile_dB, seuil {SCORE_THRESHOLD})")
            round_kept = 0
            for score, peak, db, pct, intensity, reason in scored:
                kept = score >= SCORE_THRESHOLD
                mark = "✓ gardé " if kept else "✗ rejeté"
                print(f"    [{fmt(peak)}] {mark} score={score:.1f} (intensité={intensity:.0f}, dB={db:+.1f}/{pct:.0f}e pctl) {reason}")
                if kept:
                    total_kept += 1
                    round_kept += 1
                    all_moments.append({
                        "peak": peak,
                        "start": max(0, peak - PRE),
                        "end": peak + POST,
                        "db": round(db, 1),
                        "score": round(score, 1),
                        "reason": reason,
                    })
                else:
                    total_rejected += 1

            print(f"  → Round {idx+1}/{len(windows)} : {round_kept} gardés / {len(scored)} proposés")
            if step_summary:
                with open(step_summary, "a") as f:
                    f.write(f"| {idx+1}/{len(windows)} | {fmt(start)}-{fmt(end)} | {len(lines)} | {len(scored)} | {round_kept} |\n")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    all_moments.sort(key=lambda m: m["start"])
    print(f"\n{'='*50}")
    print(f"Total : {total_kept} moments gardés / {total_rejected} rejetés (seuil score {SCORE_THRESHOLD}), sur {len(windows)} rounds")
    print(f"Tokens Haiku — input: {total_in}, output: {total_out}")

    os.makedirs(os.path.dirname(MOMENTS_JSON), exist_ok=True)
    with open(MOMENTS_JSON, "w") as f:
        json.dump(all_moments, f, indent=2, ensure_ascii=False)
    print(f"\nSauvegardé : {MOMENTS_JSON}")
    print(f"Lance le download : python3 {os.path.join(BASE_DIR, 'src/urkl_download.py')} 0")


if __name__ == "__main__":
    main()

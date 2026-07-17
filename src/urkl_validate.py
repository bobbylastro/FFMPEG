#!/usr/bin/env python3
"""
Serveur de validation des clips URKL. Les clips sont streamés depuis R2.
Usage: python3 src/urkl_validate.py [port]
"""
import os, sys, json, threading, subprocess, urllib.parse, tempfile

sys.path.insert(0, "/workspaces/FFMPEG/src")
import urkl_r2 as r2lib

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT          = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
MOMENTS_JSON  = "/workspaces/FFMPEG/data/urkl_moments.json"
URKL_NOTIFIER = "/workspaces/FFMPEG/src/urkl_notifier.py"
COOKIES       = "/workspaces/FFMPEG/data/yt_cookies.txt"

compile_log    = []
compile_result = {}
compile_event  = threading.Event()
compile_lock   = threading.Lock()

# ── Thumbs ─────────────────────────────────────────────────────────────────

THUMB_CACHE = {}

def get_or_make_thumb(fname: str) -> bytes | None:
    """Returns JPEG bytes for the thumbnail, generating + uploading if needed."""
    if fname in THUMB_CACHE:
        return THUMB_CACHE[fname]

    r2 = r2lib.client()

    if not r2lib.thumb_exists(fname, r2):
        # Download clip to tmp, extract frame, upload thumb
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            clip_tmp = tf.name
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            thumb_tmp = tf.name
        try:
            r2lib.download_clip(fname, clip_tmp, r2)
            subprocess.run(
                ["ffmpeg", "-y", "-ss", "7", "-i", clip_tmp,
                 "-vframes", "1", "-q:v", "4", "-vf", "scale=320:-1", thumb_tmp],
                capture_output=True
            )
            if os.path.exists(thumb_tmp) and os.path.getsize(thumb_tmp) > 0:
                r2lib.upload_thumb(thumb_tmp, fname, r2)
        finally:
            for p in (clip_tmp, thumb_tmp):
                try: os.unlink(p)
                except: pass

    # Fetch from R2
    try:
        obj = r2lib.client().get_object(Bucket=r2lib.R2_BUCKET, Key=r2lib.thumb_key(fname))
        data = obj["Body"].read()
        THUMB_CACHE[fname] = data
        return data
    except Exception:
        return None


# ── Compilation ─────────────────────────────────────────────────────────────

def do_compile(validated_files: list):
    global compile_result
    compile_log.clear()
    compile_log.append(f"Compilation de {len(validated_files)} clips depuis R2...")

    r2 = r2lib.client()
    tmp_dir = tempfile.mkdtemp(prefix="urkl_compile_")
    local_clips = []

    try:
        for fname in validated_files:
            local_path = os.path.join(tmp_dir, fname)
            compile_log.append(f"  Téléchargement {fname} depuis R2...")
            r2lib.download_clip(fname, local_path, r2)
            local_clips.append(local_path)

        compile_log.append("ffmpeg concat en cours...")
        list_path = os.path.join(tmp_dir, "_concat.txt")
        out_path  = os.path.join(tmp_dir, "compilation_urkl.mp4")

        with open(list_path, "w") as f:
            for p in local_clips:
                f.write(f"file '{p}'\n")

        result = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", out_path],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            compile_log.append(f"ERREUR ffmpeg : {result.stderr[-300:]}")
            compile_result = {"ok": False, "error": result.stderr[-300:]}
            compile_event.set()
            return

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        compile_log.append(f"Compilation OK : {size_mb:.1f} MB")

        compile_log.append("Envoi notification (R2 + email)...")
        nr = subprocess.run(
            ["python3", URKL_NOTIFIER, out_path, str(len(validated_files))],
            capture_output=True, text=True, cwd="/workspaces/FFMPEG"
        )
        for line in (nr.stdout or "").strip().split("\n"):
            if line: compile_log.append(line)
        if nr.stderr:
            compile_log.append(f"[stderr] {nr.stderr.strip()[-200:]}")

        if nr.returncode == 0:
            compile_result = {"ok": True, "size_mb": round(size_mb, 1)}
        else:
            compile_result = {"ok": False, "error": f"Notifier exit {nr.returncode}"}

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        compile_event.set()


# ── HTML ────────────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>URKL — Validation</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #111; color: #eee; font-family: sans-serif; }
header { background: #1a1a1a; padding: 14px 20px; border-bottom: 1px solid #333;
         display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
header h1 { font-size: 1.1rem; flex: 1; }
#stats { font-size: .85rem; color: #aaa; white-space: nowrap; }
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
button { padding: 7px 14px; border: none; border-radius: 4px; cursor: pointer;
         font-size: .85rem; font-weight: bold; }
#btn-validate-sel { background: #22c55e; color: #000; }
#btn-refuse-sel   { background: #ef4444; color: #fff; }
#btn-all          { background: #444; color: #eee; }
#btn-none         { background: #333; color: #aaa; }
#btn-compile      { background: #f59e0b; color: #000; }
#btn-validate-sel:disabled,#btn-refuse-sel:disabled { opacity:.4; cursor:default; }

#grid { display:flex; flex-wrap:wrap; gap:12px; padding:16px; }

.card { background:#1c1c1c; border:2px solid #333; border-radius:8px;
        width:260px; overflow:hidden; }
.card.selected  { border-color:#60a5fa; }
.card.validated { border-color:#22c55e; }
.card.refused   { border-color:#ef4444; opacity:.5; }

.card-top { position:relative; }
.card-top video { width:100%; height:146px; object-fit:cover; display:block; background:#000; }
.card-top label { position:absolute; top:6px; left:6px; z-index:2; }
.card-top input[type=checkbox] { width:18px; height:18px; accent-color:#60a5fa; cursor:pointer; }
.badge { position:absolute; top:6px; right:6px; padding:2px 7px; border-radius:10px;
         font-size:.7rem; font-weight:bold; }
.badge-v { background:#22c55e; color:#000; }
.badge-r { background:#ef4444; color:#fff; }
.badge-p { background:#444; color:#ccc; }

.card-body { padding:8px 10px; }
.card-body .name { font-size:.85rem; font-weight:bold; color:#ddd; }
.card-body .meta { font-size:.75rem; color:#888; margin-top:2px; }
.card-actions { display:flex; gap:6px; padding:8px 10px; border-top:1px solid #2a2a2a; }
.card-actions button { flex:1; padding:5px; font-size:.75rem; }
.btn-v { background:#16a34a; color:#fff; }
.btn-r { background:#b91c1c; color:#fff; }

#compile-panel { display:none; position:fixed; inset:0; background:rgba(0,0,0,.85);
                 align-items:center; justify-content:center; z-index:100; }
#compile-panel.show { display:flex; }
#compile-box { background:#1a1a1a; border:1px solid #333; border-radius:10px;
               padding:24px; width:580px; max-width:95vw; }
#compile-box h2 { margin-bottom:12px; }
#compile-log { background:#111; border:1px solid #222; padding:10px; border-radius:4px;
               font-family:monospace; font-size:.8rem; max-height:320px; overflow-y:auto;
               white-space:pre-wrap; }
#compile-close { margin-top:14px; float:right; background:#333; color:#eee; }
</style>
</head>
<body>
<header>
  <h1>🤖 URKL — Validation</h1>
  <span id="stats">Chargement...</span>
  <div class="toolbar">
    <button id="btn-all"  onclick="selectAll()">Tout cocher</button>
    <button id="btn-none" onclick="selectNone()">Tout décocher</button>
    <button id="btn-validate-sel" onclick="batchValidate()" disabled>Valider sélection</button>
    <button id="btn-refuse-sel"   onclick="batchRefuse()"   disabled>Refuser sélection</button>
    <button id="btn-compile" onclick="startCompile()">Compiler</button>
  </div>
</header>
<div id="grid"></div>
<div id="compile-panel">
  <div id="compile-box">
    <h2>Compilation…</h2>
    <div id="compile-log"></div>
    <div style="margin-top:14px;display:flex;gap:10px;justify-content:flex-end;">
      <button id="btn-cleanup" onclick="cleanupCompiled()"
              style="display:none;background:#ef4444;color:#fff;">🗑️ Supprimer clips compilés</button>
      <button id="compile-close" onclick="closeCompile()" style="background:#333;color:#eee;">Fermer</button>
    </div>
  </div>
</div>
<script>
const selected = new Set();

function updateSelButtons() {
  const d = selected.size === 0;
  document.getElementById('btn-validate-sel').disabled = d;
  document.getElementById('btn-refuse-sel').disabled   = d;
}
function toggleSelect(fname, cb) {
  cb.checked ? selected.add(fname) : selected.delete(fname);
  cb.closest('.card').classList.toggle('selected', cb.checked);
  updateSelButtons();
}
function selectAll() {
  document.querySelectorAll('.card input[type=checkbox]').forEach(cb => {
    cb.checked = true; selected.add(cb.dataset.file);
    cb.closest('.card').classList.add('selected');
  });
  updateSelButtons();
}
function selectNone() {
  document.querySelectorAll('.card input[type=checkbox]').forEach(cb => {
    cb.checked = false; selected.delete(cb.dataset.file);
    cb.closest('.card').classList.remove('selected');
  });
  updateSelButtons();
}
async function api(path, body) {
  return fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                      body: JSON.stringify(body)});
}
async function setStatus(fname, action) {
  await api('/api/' + action, {file: fname});
  loadClips();
}
async function batchValidate() {
  if (!selected.size) return;
  await api('/api/validate_batch', {files:[...selected]});
  selectNone(); loadClips();
}
async function batchRefuse() {
  if (!selected.size) return;
  await api('/api/refuse_batch', {files:[...selected]});
  selectNone(); loadClips();
}
async function loadClips() {
  const clips = await (await fetch('/api/clips')).json();
  const v = clips.filter(c=>c.status==='validated').length;
  const r = clips.filter(c=>c.status==='refused').length;
  const p = clips.filter(c=>c.status==='pending').length;
  document.getElementById('stats').textContent =
    `${clips.length} clips — ✅ ${v} · ❌ ${r} · ⏳ ${p}`;
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  clips.forEach(c => {
    const isSel = selected.has(c.file);
    const badge = c.status==='validated' ? '<span class="badge badge-v">✅ OK</span>'
                : c.status==='refused'   ? '<span class="badge badge-r">❌</span>'
                : '<span class="badge badge-p">⏳</span>';
    const cls = 'card'+(isSel?' selected':'')+(c.status==='validated'?' validated':'')+(c.status==='refused'?' refused':'');
    const div = document.createElement('div');
    div.className = cls; div.dataset.file = c.file;
    div.innerHTML = `
      <div class="card-top">
        <video src="${c.url}" poster="/thumbs/${c.file}" preload="none" controls></video>
        <label><input type="checkbox" data-file="${c.file}" ${isSel?'checked':''}
               onchange="toggleSelect('${c.file}',this)"></label>
        ${badge}
      </div>
      <div class="card-body">
        <div class="name">${c.file}</div>
        <div class="meta">${c.db ? c.db + ' dB' : ''}</div>
      </div>
      <div class="card-actions">
        <button class="btn-v" onclick="setStatus('${c.file}','validate')">✅ Valider</button>
        <button class="btn-r" onclick="setStatus('${c.file}','refuse')">❌ Refuser</button>
      </div>`;
    grid.appendChild(div);
  });
}
let pollInterval;
function startCompile() {
  document.getElementById('compile-panel').classList.add('show');
  document.getElementById('compile-log').textContent = 'Démarrage...';
  document.getElementById('btn-cleanup').style.display = 'none';
  fetch('/api/compile', {method:'POST'});
  pollInterval = setInterval(async () => {
    const d = await (await fetch('/api/log')).json();
    document.getElementById('compile-log').textContent = d.log.join('\n');
    document.getElementById('compile-log').scrollTop = 9999;
    if (d.done) {
      clearInterval(pollInterval);
      if (d.result?.ok) {
        document.getElementById('compile-log').textContent += '\n\n✅ Compilation terminée !';
        document.getElementById('btn-cleanup').style.display = 'inline-block';
      } else {
        document.getElementById('compile-log').textContent += '\n\n❌ ' + (d.result?.error||'?');
      }
    }
  }, 1500);
}
async function cleanupCompiled() {
  document.getElementById('btn-cleanup').textContent = 'Suppression...';
  document.getElementById('btn-cleanup').disabled = true;
  await fetch('/api/cleanup', {method:'POST'});
  document.getElementById('compile-log').textContent += '\n🗑️ Clips compilés supprimés de R2.';
  document.getElementById('btn-cleanup').style.display = 'none';
  closeCompile();
  loadClips();
}
function closeCompile() {
  document.getElementById('compile-panel').classList.remove('show');
  clearInterval(pollInterval);
}
loadClips();
</script>
</body>
</html>"""


# ── HTTP Handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in ("/", "/index.html"):
            body = HTML_PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/clips":
            r2 = r2lib.client()
            clips_in_r2 = r2lib.list_clips(r2)
            state = r2lib.load_state(r2)

            # Load dB info from moments if available
            db_map = {}
            if os.path.exists(MOMENTS_JSON):
                with open(MOMENTS_JSON) as f:
                    moments = json.load(f)
                all_starts = [m["start"] for m in moments]
                for idx, m in enumerate(moments):
                    db_map[f"clip_{idx+1:02d}.mp4"] = m["db"]

            clips = []
            for fname in clips_in_r2:
                clips.append({
                    "file": fname,
                    "url":  r2lib.clip_url(fname),
                    "status": state.get(fname, "pending"),
                    "db": db_map.get(fname),
                })
            self.send_json(clips)

        elif path == "/api/log":
            with compile_lock:
                done = compile_event.is_set()
            self.send_json({"log": list(compile_log), "done": done,
                            "result": compile_result if done else None})

        elif path.startswith("/thumbs/"):
            fname = path[len("/thumbs/"):]
            data = get_or_make_thumb(fname)
            if data:
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", len(data))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        global compile_event, compile_result
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/validate":
            state = r2lib.load_state()
            state[body["file"]] = "validated"
            r2lib.save_state(state)
            self.send_json({"ok": True})

        elif path == "/api/refuse":
            fname = body["file"]
            r2 = r2lib.client()
            state = r2lib.load_state(r2)
            state.pop(fname, None)
            r2lib.save_state(state, r2)
            r2lib.delete_clip(fname, r2)
            THUMB_CACHE.pop(fname, None)
            self.send_json({"ok": True})

        elif path == "/api/validate_batch":
            state = r2lib.load_state()
            for f in body.get("files", []): state[f] = "validated"
            r2lib.save_state(state)
            self.send_json({"ok": True})

        elif path == "/api/refuse_batch":
            r2 = r2lib.client()
            state = r2lib.load_state(r2)
            for f in body.get("files", []):
                state.pop(f, None)
                r2lib.delete_clip(f, r2)
                THUMB_CACHE.pop(f, None)
            r2lib.save_state(state, r2)
            self.send_json({"ok": True})

        elif path == "/api/cleanup":
            r2 = r2lib.client()
            state = r2lib.load_state(r2)
            validated = [f for f, s in state.items() if s == "validated"]
            for f in validated:
                r2lib.delete_clip(f, r2)
                THUMB_CACHE.pop(f, None)
            r2lib.save_state({}, r2)
            self.send_json({"ok": True, "deleted": len(validated)})

        elif path == "/api/compile":
            state = r2lib.load_state()
            validated = sorted(f for f, s in state.items() if s == "validated")
            if not validated:
                self.send_json({"ok": False, "error": "Aucun clip validé"}, 400)
                return
            compile_event.clear()
            compile_result.clear()
            compile_log.clear()
            t = threading.Thread(target=do_compile, args=(validated,), daemon=True)
            t.start()
            self.send_json({"ok": True, "count": len(validated)})

        else:
            self.send_response(404); self.end_headers()


if __name__ == "__main__":
    r2 = r2lib.client()
    clips_count = len(r2lib.list_clips(r2))
    state = r2lib.load_state(r2)
    v = sum(1 for s in state.values() if s == "validated")
    print(f"Serveur URKL démarré sur http://0.0.0.0:{PORT}")
    print(f"Clips dans R2 : {clips_count}  (validés: {v})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

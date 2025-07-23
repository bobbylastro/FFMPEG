import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/render', methods=['POST'])
def render_video():
    # Exemple très simple : convertit une image en vidéo 5s (placeholder)
    # En vrai, tu adapteras la commande selon ton besoin
    
    input_image = "input.jpg"  # à remplacer par ta source
    output_video = "output.mp4"
    
    cmd = [
        "ffmpeg",
        "-loop", "1",
        "-i", input_image,
        "-c:v", "libx264",
        "-t", "5",
        "-pix_fmt", "yuv420p",
        output_video
    ]
    
    try:
        subprocess.run(cmd, check=True)
        return jsonify({"status": "success", "output": output_video})
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

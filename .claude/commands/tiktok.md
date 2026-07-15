Run the TikTok/Shorts generation pipeline by executing `python run_tiktok.py` from /workspaces/FFMPEG.

This fetches the best clips from Medal.tv (one per game across 5 games), downloads them, and generates 5 vertical 9:16 videos (max 59s each) saved in output/tiktok/.

After it completes, report:
- The list of generated files with their sizes
- The title and view count of the clip chosen for each game
- Any clips that failed to download or encode

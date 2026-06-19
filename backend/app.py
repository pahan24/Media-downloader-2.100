"""
VidSnap Backend — Flask + yt-dlp (Fixed & Robust Version)
Supports: YouTube, TikTok, Instagram, Facebook
Deploy FREE on Railway or Render
"""

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import uuid
import glob
import tempfile
import threading
import shutil
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins="*", supports_credentials=False)

DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "vidsnap")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Check if ffmpeg is available
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
logger.info(f"ffmpeg available: {FFMPEG_AVAILABLE}")


# ─────────────────────────────────────────────────
# CORS preflight — OPTIONS requests handle karanna
# ─────────────────────────────────────────────────
@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"]  = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp


# ─────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────
@app.route("/health", methods=["GET", "OPTIONS"])
def health():
    return jsonify({
        "status":           "ok",
        "message":          "VidSnap backend is live! ⚡",
        "ffmpeg_available": FFMPEG_AVAILABLE,
        "yt_dlp_version":   yt_dlp.version.__version__,
    })


# ─────────────────────────────────────────────────
# Build format string with proper fallbacks
# ─────────────────────────────────────────────────
def build_format(format_id: str) -> str:
    """
    Format string ekak hadanawa — ffmpeg nathoth fallback use karanawa.
    bestvideo+bestaudio = ffmpeg ona — nathoth best single file use karanawa.
    """
    if format_id in ("bestaudio", "audio"):
        if FFMPEG_AVAILABLE:
            return "bestaudio/best"
        return "bestaudio/best"  # yt-dlp handles this even without ffmpeg sometimes

    if format_id == "best":
        return "best/bestvideo+bestaudio"

    # Height-based format: eg "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    if "bestvideo" in format_id:
        # Extract height from format string
        try:
            h = int(format_id.split("<=")[1].split("]")[0])
        except Exception:
            return "best"

        if FFMPEG_AVAILABLE:
            return (
                f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
                f"/bestvideo[height<={h}]+bestaudio"
                f"/best[height<={h}]/best"
            )
        else:
            # Without ffmpeg, use pre-merged formats only
            return f"best[height<={h}]/best[height<=720]/best"

    return format_id  # Use as-is if custom


# ─────────────────────────────────────────────────
# Find downloaded file (extension guess karanna bari — glob use karanawa)
# ─────────────────────────────────────────────────
def find_downloaded_file(uid: str) -> str | None:
    pattern = os.path.join(DOWNLOAD_DIR, f"{uid}.*")
    files   = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for f in files:
        if os.path.isfile(f) and os.path.getsize(f) > 0:
            return f
    return None


# ─────────────────────────────────────────────────
# Get video info + formats
# ─────────────────────────────────────────────────
@app.route("/api/info", methods=["POST", "OPTIONS"])
def get_info():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL ekak required!"}), 400

    ydl_opts = {
        "quiet":       True,
        "no_warnings": True,
        # Uncomment for cookies:
        # "cookiesfrombrowser": ("chrome",),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            vcodec = f.get("vcodec", "none") or "none"
            acodec = f.get("acodec", "none") or "none"
            formats.append({
                "format_id": f.get("format_id"),
                "ext":       f.get("ext", "mp4"),
                "height":    f.get("height"),
                "width":     f.get("width"),
                "vcodec":    vcodec,
                "acodec":    acodec,
                "filesize":  f.get("filesize"),
                "tbr":       f.get("tbr"),
                "abr":       f.get("abr"),
                "has_video": vcodec != "none",
                "has_audio": acodec != "none",
            })

        return jsonify({
            "title":            info.get("title", "Unknown"),
            "thumbnail":        info.get("thumbnail", ""),
            "duration":         info.get("duration", 0),
            "uploader":         info.get("uploader", ""),
            "view_count":       info.get("view_count", 0),
            "formats":          formats,
            "ffmpeg_available": FFMPEG_AVAILABLE,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        logger.error(f"yt-dlp info error: {msg}")
        # User-friendly error messages
        if "Private video"     in msg: return jsonify({"error": "Private video — login required"}), 422
        if "age-restricted"    in msg: return jsonify({"error": "Age-restricted video — cookies required"}), 422
        if "not available"     in msg: return jsonify({"error": "Video not available in your region"}), 422
        if "Unsupported URL"   in msg: return jsonify({"error": "Unsupported URL — YouTube/TikTok/Instagram/Facebook vitharai support wennet"}), 422
        return jsonify({"error": f"yt-dlp error: {msg[:200]}"}), 422
    except Exception as e:
        logger.error(f"Info error: {e}", exc_info=True)
        return jsonify({"error": str(e)[:300]}), 500


# ─────────────────────────────────────────────────
# Download video / audio — stream karanawa (memory safe)
# ─────────────────────────────────────────────────
@app.route("/api/download", methods=["POST", "OPTIONS"])
def download_video():
    data      = request.get_json(silent=True) or {}
    url       = data.get("url", "").strip()
    format_id = data.get("format_id", "best")

    if not url:
        return jsonify({"error": "URL ekak required!"}), 400

    uid         = str(uuid.uuid4())
    output_tmpl = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")
    is_audio    = "bestaudio" in format_id or format_id == "audio"
    fmt_string  = build_format(format_id)

    ydl_opts = {
        "format":    fmt_string,
        "outtmpl":   output_tmpl,
        "quiet":     True,
        "no_warnings": True,
        "postprocessors": [],
        # Uncomment for cookies:
        # "cookiesfrombrowser": ("chrome",),
    }

    if is_audio and FFMPEG_AVAILABLE:
        ydl_opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]
    elif is_audio:
        # ffmpeg nathoth — best audio file as-is download karanawa (m4a/webm)
        ydl_opts["format"] = "bestaudio/best"

    if FFMPEG_AVAILABLE:
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info  = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        # File eka find karanawa (glob use karanawa — extension guess wenath bari)
        file_path = find_downloaded_file(uid)
        if not file_path:
            logger.error(f"Downloaded file not found for uid={uid}")
            return jsonify({"error": "Downloaded file not found. Format support nehe wage thiyanawa — 'Best' try karanna."}), 500

        ext = os.path.splitext(file_path)[1].lstrip(".")

        # Mime type
        mime_map = {
            "mp4": "video/mp4", "webm": "video/webm", "mkv": "video/x-matroska",
            "mp3": "audio/mpeg", "m4a": "audio/mp4", "opus": "audio/ogg",
            "ogg": "audio/ogg", "wav": "audio/wav",
        }
        mime = mime_map.get(ext, "application/octet-stream")

        # Safe filename
        safe = "".join(c for c in title if c.isalnum() or c in " -_()[]").strip()[:80]
        dl_name = f"{safe}.{ext}" if safe else f"vidsnap.{ext}"

        # Cleanup after 10 minutes
        def cleanup(path):
            try: os.remove(path)
            except: pass
        threading.Timer(600, cleanup, args=[file_path]).start()

        # Stream karanawa (memory safe for large files)
        file_size = os.path.getsize(file_path)

        def generate():
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    yield chunk

        headers = {
            "Content-Disposition": f'attachment; filename="{dl_name}"',
            "Content-Type":        mime,
            "Content-Length":      str(file_size),
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        }

        return Response(generate(), headers=headers, status=200)

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        logger.error(f"yt-dlp download error: {msg}")
        if "Private"        in msg: return jsonify({"error": "Private video — login cookies required"}), 422
        if "age-restricted" in msg: return jsonify({"error": "Age-restricted — cookies required"}), 422
        if "ffmpeg"         in msg: return jsonify({"error": "ffmpeg not installed on server. 'Best' format try karanna."}), 422
        return jsonify({"error": f"Download error: {msg[:300]}"}), 422
    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        return jsonify({"error": str(e)[:300]}), 500


# ─────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"VidSnap backend starting on port {port} | ffmpeg={FFMPEG_AVAILABLE}")
    app.run(host="0.0.0.0", port=port, debug=False)

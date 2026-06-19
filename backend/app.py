"""
VidSnap Backend — Flask + yt-dlp
Supports: YouTube, TikTok, Instagram, Facebook
Deploy FREE on Railway or Render
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import tempfile
import threading
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Allow all origins — tighten in production by setting specific frontend URL
CORS(app, origins="*")

DOWNLOAD_DIR = tempfile.gettempdir()


# ─────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "message": "VidSnap backend is live! ⚡"})


# ─────────────────────────────────────────────────
# Get video info + available formats
# ─────────────────────────────────────────────────
@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL required"}), 400

    ydl_opts = {
        "quiet":       True,
        "no_warnings": True,
        # Uncomment and fill if you need cookies for age-restricted / private content:
        # "cookiesfrombrowser": ("chrome",),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        for f in info.get("formats", []):
            formats.append({
                "format_id": f.get("format_id"),
                "ext":       f.get("ext", "mp4"),
                "height":    f.get("height"),
                "width":     f.get("width"),
                "vcodec":    f.get("vcodec", "none"),
                "acodec":    f.get("acodec", "none"),
                "filesize":  f.get("filesize"),
                "tbr":       f.get("tbr"),
                "abr":       f.get("abr"),
            })

        return jsonify({
            "title":      info.get("title", "Unknown"),
            "thumbnail":  info.get("thumbnail", ""),
            "duration":   info.get("duration", 0),
            "uploader":   info.get("uploader", ""),
            "view_count": info.get("view_count", 0),
            "formats":    formats,
        })

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp info error: {e}")
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"Info error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────
# Download video / audio
# ─────────────────────────────────────────────────
@app.route("/api/download", methods=["POST"])
def download_video():
    data      = request.get_json(silent=True) or {}
    url       = data.get("url", "").strip()
    format_id = data.get("format_id", "best")

    if not url:
        return jsonify({"error": "URL required"}), 400

    uid         = str(uuid.uuid4())
    output_tmpl = os.path.join(DOWNLOAD_DIR, f"{uid}.%(ext)s")

    is_audio = "bestaudio" in format_id or format_id == "audio"

    ydl_opts = {
        "format":              format_id,
        "outtmpl":             output_tmpl,
        "quiet":               True,
        "no_warnings":         True,
        "merge_output_format": "mp4",
        "postprocessors":      [],
        # Uncomment for cookies:
        # "cookiesfrombrowser": ("chrome",),
    }

    if is_audio:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key":              "FFmpegExtractAudio",
            "preferredcodec":   "mp3",
            "preferredquality": "192",
        }]

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "video")

        # Locate the downloaded file
        expected_ext = "mp3" if is_audio else "mp4"
        file_path    = os.path.join(DOWNLOAD_DIR, f"{uid}.{expected_ext}")

        if not os.path.exists(file_path):
            # Fallback: scan for any file with our uid prefix
            for fname in os.listdir(DOWNLOAD_DIR):
                if fname.startswith(uid):
                    file_path    = os.path.join(DOWNLOAD_DIR, fname)
                    expected_ext = fname.rsplit(".", 1)[-1]
                    break

        if not os.path.exists(file_path):
            return jsonify({"error": "Downloaded file not found"}), 500

        # Safe filename for Content-Disposition
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_()").strip()[:80]
        dl_name    = f"{safe_title}.{expected_ext}" if safe_title else f"video.{expected_ext}"

        # Delete temp file 5 minutes after sending
        def cleanup(path):
            try:
                os.remove(path)
            except Exception:
                pass

        threading.Timer(300, cleanup, args=[file_path]).start()

        return send_file(
            file_path,
            as_attachment=True,
            download_name=dl_name,
            mimetype="application/octet-stream",
        )

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp download error: {e}")
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"VidSnap backend starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

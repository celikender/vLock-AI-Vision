"""Local camera page plus explicit captured-photo analysis. No automatic uploads."""
from pathlib import Path
from uuid import UUID
from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from analysis import AnalysisError, analyze_photo
from eyes import locate_eyes

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(ROOT / "static"))
app.config["MAX_CONTENT_LENGTH"] = 9 * 1024 * 1024


@app.before_request
def protect_local_api():
    if request.host not in {"localhost:5050", "127.0.0.1:5050"}:
        return jsonify(error="Open this app at localhost:5050."), 403
    if request.method == "POST" and request.headers.get("Origin") != request.host_url.rstrip("/"):
        return jsonify(error="Photo requests must come from this page."), 403


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/analyze")
def analyze():
    mode = request.form.get("mode", "describe")
    if mode not in {"describe", "eyes"}:
        return jsonify(error="Unknown analysis mode."), 400
    image = request.files.get("photo")
    prompt = request.form.get("prompt", "").strip()
    capture_id = request.form.get("capture_id", "")
    try:
        UUID(capture_id)
    except ValueError:
        return jsonify(error="Capture a photo before analyzing."), 400
    if len(prompt) > 2000:
        return jsonify(error="Keep the question under 2,000 characters."), 400
    if image is None or image.mimetype != "image/jpeg":
        return jsonify(error="A captured JPEG photo is required."), 400
    jpeg = image.read(5 * 1024 * 1024 + 1)
    if len(jpeg) > 5 * 1024 * 1024:
        return jsonify(error="Photo is too large. Maximum size is 5 MB."), 413
    if not jpeg.startswith(b"\xff\xd8\xff") or not jpeg.endswith(b"\xff\xd9"):
        return jsonify(error="The captured photo is not a valid JPEG file."), 400
    try:
        result = locate_eyes(jpeg) if mode == "eyes" else analyze_photo(jpeg, prompt)
    except AnalysisError as error:
        return jsonify(error=str(error)), error.status
    return jsonify(capture_id=capture_id, **result)


@app.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return jsonify(error="Upload is too large. Capture a smaller photo (maximum 5 MB)."), 413


@app.after_request
def disable_cache(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)




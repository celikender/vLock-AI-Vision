# Camera and photo analysis playground

Start the PC camera, capture a photo, ask a question, and display Claude's answer.

## Run from VS Code

```powershell
cd "C:\Users\ec-en\Desktop\vLock-AI Vision"
.\.venv\Scripts\python.exe -m pip install -r playground/camera/requirements.txt
.\.venv\Scripts\python.exe playground/camera/app.py
```

Keep the terminal running. Open http://localhost:5050 in Chrome or Edge.

1. Click Start camera and allow camera access.
2. Click Capture photo. The captured image appears below the preview.
3. Enter a question such as "How many pens are in the photo?", or leave it blank
   for a general description.
4. Click Analyze photo. The answer, model name, and request time appear below it.
5. Capture another photo to clear the previous output and repeat.

Live video stays in the browser. Analyze uploads only the displayed captured
JPEG and question through the local server to the Anthropic Claude API.
No image or answer is saved by the app. Download photo saves a JPEG on request.
Cloud API usage may incur charges; provider retention is governed by your provider.
The app displays model output as plain text, not executable HTML.

## Model setup

This version uses the Anthropic Claude cloud API. Local-model selection
is not implemented. Add these values to the project .env:

```text
ANTHROPIC_API_KEY=your-key-here
ANTHROPIC_MODEL=claude-sonnet-5-5
```

Keep the actual key local. It stays on the Python side; the browser never receives
it. The app reports missing credentials, rejected access, API limits, and timeouts
without returning raw provider errors. Settings are read on each analysis; shell environment variables take precedence.
Request timeout is 120 seconds with no automatic retries. Prompt limit is 2,000
characters; JPEG limit is 5 MB. Counting accuracy must be evaluated with actual photos.

## Read the code

- app.py: page server, upload validation, and analysis endpoint.
- analysis.py: default prompt and one image-plus-text API request.
- static/index.html: camera controls, optional question, and model output.
- static/app.js: camera capture, upload action, loading, and error display.
- static/style.css: simple layout.
- test_analysis.py: offline request/error checks with mocked provider responses.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s playground/camera -p test_analysis.py -v
```

Offline tests do not establish API key validity, model access, or model accuracy.
The owner verifies real camera capture and cloud output from the page. No SAM,
video streaming to a model, or Raspberry Pi feed is implemented in this step.

[Official Claude image input reference](https://platform.claude.com/docs/en/build-with-claude/vision)


## Eye-box experiment

After capturing a photo, click Box eyes. This uses a fixed eye-location prompt;
the normal Analyze photo button still uses your optional question. Claude returns
structured JSON with one rectangle per visible eye. The browser draws green
squares around those regions on a second copy titled Annotated photo.

The original capture remains above. No live video is sent. Position estimates
are approximate and must be checked visually. This is not SAM segmentation or
continuous eye tracking. No visible eyes is a valid empty result.

For coordinate consistency, eyes.py sends a resized copy (maximum edge 1008px),
asks for absolute pixel coordinates, validates the boxes against those dimensions,
and returns the coordinate-system dimensions. overlay.js scales them to the
original captured image and draws bounded squares on a canvas.

Additional files:
- eyes.py: resized image, JSON schema, eye prompt, coordinate validation.
- static/overlay.js: canvas drawing with source-image coordinate scaling.
- test_eyes.py and test_overlay.cjs: generated-image and geometry tests.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s playground/camera -p "test_*.py" -v
node playground/camera/test_overlay.cjs
```

The eye-box mode requires a Claude model supporting structured JSON output.
[Coordinate guidance](https://platform.claude.com/docs/en/build-with-claude/vision-coordinates)

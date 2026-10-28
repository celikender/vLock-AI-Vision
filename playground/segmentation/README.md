# SAM 3.1 captured-photo experiment

In the main PC app, Capture photo, scroll to SAM 3.1 experiment, select Local GPU
or Cloud API, enter one object phrase (for example monitor), and click Segment.
Both modes use the same capture, reduced to a maximum edge of 1008 pixels.
Results show colored pixel masks with outlines, object count, elapsed time, and
an annotated PNG download. The original capture and Claude result remain visible.
These are model predictions, not exact geometric measurements or tracking.

## Cloud API

In the root local .env set META_API_KEY to your Meta developer API key and
META_SAM_MODEL=sam-3.1. Settings reload per request. No key goes to the browser.
MODEL_API_KEY is accepted as an alternative. The endpoint is fixed to Meta's API.
Cloud mode sends the selected JPEG and prompt to Meta only when Segment is clicked.
Use Check setup to see key presence; presence does not verify account access.

## Local GPU on Windows through Ubuntu/WSL

The local worker runs separately from the PC UI, on loopback port 5052.
The isolated Python environment is ~/.local/share/vlock-vision/sam-env inside Ubuntu.
The model cache uses Hugging Face's default user cache; neither location is tracked.

After obtaining approval at https://huggingface.co/facebook/sam3.1, open Ubuntu:

```bash
~/.local/share/vlock-vision/sam-env/bin/hf auth login
~/.local/share/vlock-vision/sam-env/bin/hf download facebook/sam3.1 sam3.1_multiplex.pt
```

Enter credentials only into your terminal, never chat or source files.
Then run from the project PowerShell terminal:

```powershell
./playground/segmentation/start_local.ps1
```

Keep that terminal open. In the app select Local GPU and Check setup.
The first segmentation loads the model; later requests reuse it. The worker uses
the official SAM 3.1 predictor on a temporary one-frame session, bf16 inference,
eight object slots, CPU frame/state offloading, no compilation, and no Flash
Attention 3 dependency. Temporary captures are removed when the request finishes.
Local images are not uploaded. Local failure never switches to cloud automatically.
An 8 GB GPU may still run out of memory; the UI reports that explicitly. Do not
claim a latency or memory result until a real checkpoint-backed run succeeds.
Peak VRAM reports allocated GPU tensor memory, not total system GPU usage.
Cloud and local elapsed timings include their respective request/processing costs;
the local first call includes model load and is not comparable to a warm run.

## Reproduce runtime setup

Install python3.12-venv, git, libgl1, and libglib2.0-0 through Ubuntu apt first.
Create the isolated environment and install official PyTorch CUDA wheels:

```bash
python3 -m venv ~/.local/share/vlock-vision/sam-env
~/.local/share/vlock-vision/sam-env/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'setuptools<81' pillow flask einops psutil opencv-python-headless==4.11.0.86 pycocotools scipy==1.15.3 decord
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'git+https://github.com/facebookresearch/sam3.git@f1647e8d0c1d280991f4d1b7d974c2704537fe66'
```

Official references: [model repository](https://github.com/facebookresearch/sam3),
[cloud API](https://dev.meta.ai/docs/sam/overview),
[parser](https://dev.meta.ai/docs/sam/client-libraries).

## Verification

Run `python -m unittest discover -s playground/segmentation -p 'test_*.py' -v`
in the PC environment. Tests use synthetic masks and mocked API transport.
They cover geometry, overlay output, invalid responses, missing keys and backend
separation. Live account access, checkpoint compatibility, segmentation quality,
and GPU memory fit require real inference and are separate from these checks.
## Installed-runtime check

CUDA detects the RTX 3070 Ti Laptop GPU and the SAM 3.1 builder imports successfully.
The older decord 0.6.0 wheel imports successfully but pip check reports an unsupported-platform warning.
A checkpoint-backed inference is still required to verify local memory fit and all runtime paths.

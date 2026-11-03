# Local SAM 3.1 runtime (Ubuntu / WSL)

The application starts the SAM worker by itself (`Start vLock.cmd`). This page is the
one-time setup of the CUDA environment the worker runs in. Nothing here is tracked
in Git: the environment lives in `~/.local/share/vlock-vision/sam-env` inside Ubuntu,
and the weights in the default Hugging Face cache.

## 1. Create the environment

In Ubuntu, install `python3.12-venv`, `git`, `libgl1` and `libglib2.0-0` with apt, then:

```bash
python3 -m venv ~/.local/share/vlock-vision/sam-env
~/.local/share/vlock-vision/sam-env/bin/python -m pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'setuptools<81' pillow flask einops psutil opencv-python-headless==4.11.0.86 pycocotools scipy==1.15.3 decord
~/.local/share/vlock-vision/sam-env/bin/python -m pip install 'git+https://github.com/facebookresearch/sam3.git@f1647e8d0c1d280991f4d1b7d974c2704537fe66'
```

## 2. Download the weights

Request access at https://huggingface.co/facebook/sam3.1, then in Ubuntu:

```bash
~/.local/share/vlock-vision/sam-env/bin/hf auth login
~/.local/share/vlock-vision/sam-env/bin/python '/mnt/c/Users/ec-en/Desktop/vLock-AI Vision/services/vision/runtime/download_weights.py'
```

Enter credentials only in your terminal, never in chat or source files.

## 3. Apply the session compatibility fix

The pinned runtime has the upstream start-session argument bug
([issue 544](https://github.com/facebookresearch/sam3/issues/544),
[proposed fix 543](https://github.com/facebookresearch/sam3/pull/543)):

```bash
~/.local/share/vlock-vision/sam-env/bin/python '/mnt/c/Users/ec-en/Desktop/vLock-AI Vision/services/vision/runtime/patch_runtime.py'
```

The script keeps the original source beside the patched file and refuses unexpected
layouts. Re-running it reports an already installed fix.

## How the application uses it

`services/vision/worker_process.py` runs, from the project root:

```text
wsl.exe -d Ubuntu --cd <project> --exec ~/.local/share/vlock-vision/sam-env/bin/python -m services.vision.sam_worker --preload
```

The worker listens on loopback port 5052, loads SAM 3.1 once (bf16, eight objects,
16-slot multiplex checkpoint, grounding batch size 1 for the 8 GB GPU, no compile,
no Flash Attention 3) and warms it with one blank frame. Its log is
`data/application/sam_worker.log`. Override the distribution with `VLOCK_WSL_DISTRO`
or the interpreter with `SAM_PYTHON`. See the
[performance report](reports/monitoring_performance.md) for measured timings.

Verified on 2026-11-03: RTX 3070 Ti Laptop GPU, 8 GB; the app launched the worker
from a project path containing spaces and reported ready after warm-up.

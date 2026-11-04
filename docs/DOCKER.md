# Running vLock-AI Vision with Docker

Two containers, started together by `compose.yaml`:

| Container | Image | Does | Needs |
|---|---|---|---|
| `app` | `docker/app.Dockerfile` (python:3.12-slim) | Web UI, cameras, rules, Muse, OPC UA / MQTT / REST | No GPU |
| `sam` | `docker/sam.Dockerfile` (Ubuntu 24.04 + PyTorch CUDA 12.8 + SAM 3.1) | The SAM 3.1 worker | One NVIDIA GPU (8 GB or more) |

Both use the **host network**: the app keeps its loopback-only web address
(`http://localhost:5056`), the worker stays on `127.0.0.1:5052`, and OPC UA, MQTT and
REST behave exactly as in a native start. The app runs with `VLOCK_SAM_EXTERNAL=1`: it
waits for the SAM container instead of starting WSL.

## Requirements

- An NVIDIA GPU with a recent driver. Linux: Docker Engine with the NVIDIA Container
  Toolkit. Windows: Docker Desktop with the WSL 2 backend (GPU support is included).
  AMD, Intel and Apple GPUs are not supported by the SAM runtime.
- Docker Desktop: turn on **Settings → Resources → Network → Enable host networking**.
- An approved Hugging Face account for `facebook/sam3.1` and an access token.

## Start

1. Copy `.env.example` to `.env` and set `HF_TOKEN` (and `META_API_KEY` for Muse).
2. `docker compose up -d --build`
3. Open http://localhost:5056 and create the admin account.

On the first start the `sam` container downloads the weights (about 3.5 GB) into the
`hf-models` volume with **your own** token, then checks them against the pinned SHA-256
in `services/vision/runtime/weights.sha256` before loading. The images never contain
the weights: SAM 3.1 is gated by Meta, and every user must request access themselves.
Without `HF_TOKEN` the worker starts and reports "weights missing" in the app.

Application data (zones, users, audit log, history, OPC UA certificates) lives in the
`vlock-data` volume. `.env` stays on the host and is never copied into an image
(`.dockerignore`).

## Useful commands

```bash
docker compose logs -f sam        # model download, checksum and warm-up
docker compose restart sam        # restart the worker; the app waits for it
docker compose down               # stop; volumes keep data and weights
```

## Test status

Verified on Windows (Docker Desktop, host networking on) with an RTX 3070 Ti Laptop GPU,
a Pi camera and weights copied into the volume:

- The app is reachable at `http://localhost:5056`. After recreating the app container
  this took 2-57 s, so give it up to a minute.
- Live monitoring detected a person: zone Active, `Count1` 1, on REST and on OPC UA read
  from Windows at `opc.tcp://127.0.0.1:<port>/vlock/`, so a SCADA on the same PC connects
  normally.
- A SAM check took a median of 3.13 s (6 checks, one 6.28 s outlier), against about 2.9 s
  natively. The camera ran at 11-13 fps, against about 16 fps natively.
- `docker compose restart sam`: the app showed starting, then loading, and SAM was ready
  at 59 s; the zone stayed Unknown until it returned to Active at 67 s, with no manual step.

Not verified yet: the first-start weights download with `HF_TOKEN`, an RTSP camera, MQTT
in Docker, and Linux hosts. OPC UA **Network** mode is also untested in Docker: on Docker
Desktop the network adapters the app sees belong to Docker's virtual machine, not to
Windows, so a SCADA on another PC may not reach them. For that case, use a native start
or a Linux host until this is tested.

## Not covered yet

- The Pi camera service is not containerised (it runs on the Pi).
- Multiple GPUs or several SAM workers.

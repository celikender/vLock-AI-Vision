# SAM 3.1 worker: its own GPU container. Same pinned runtime as docs/install/SAM_RUNTIME.md.
# The weights are NOT in the image: they are downloaded on first start with the user's own
# approved Hugging Face token (HF_TOKEN) into the hf-models volume, then checksum-verified.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    HF_HOME=/models VIRTUAL_ENV=/opt/sam-env PATH=/opt/sam-env/bin:$PATH
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git libgl1 libglib2.0-0 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/sam-env

# CUDA 12.8 wheels bring their own CUDA libraries; the host only needs the NVIDIA driver.
RUN pip install torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cu128
RUN pip install 'setuptools<81' pillow flask einops psutil opencv-python-headless==4.11.0.86 pycocotools \
      scipy==1.15.3 decord huggingface_hub
RUN pip install 'git+https://github.com/facebookresearch/sam3.git@f1647e8d0c1d280991f4d1b7d974c2704537fe66'

WORKDIR /app
COPY services/__init__.py services/__init__.py
COPY services/vision services/vision
# Same upstream start-session fix as the WSL runtime.
RUN python services/vision/runtime/patch_runtime.py
COPY docker/sam-entrypoint.sh /usr/local/bin/sam-entrypoint.sh
RUN chmod +x /usr/local/bin/sam-entrypoint.sh \
 && useradd --create-home --uid 10001 sam && mkdir -p /models && chown sam /models
USER sam
ENTRYPOINT ["/usr/local/bin/sam-entrypoint.sh"]

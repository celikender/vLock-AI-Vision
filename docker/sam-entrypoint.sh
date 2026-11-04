#!/bin/sh
# Start the SAM 3.1 worker. Download the gated weights once, with the user's own token.
set -e
if ! python - <<'EOF'
import sys
from huggingface_hub import try_to_load_from_cache
path = try_to_load_from_cache('facebook/sam3.1', 'sam3.1_multiplex.pt')
sys.exit(0 if isinstance(path, str) else 1)
EOF
then
  if [ -n "$HF_TOKEN" ]; then
    echo "Downloading SAM 3.1 weights with your Hugging Face token (about 3.5 GB, once)..."
    python services/vision/runtime/download_weights.py
  else
    echo "SAM 3.1 weights missing. Request access at https://huggingface.co/facebook/sam3.1," >&2
    echo "then put HF_TOKEN=<your token> in .env and restart, or mount an existing cache at /models." >&2
  fi
fi
# The worker verifies the checkpoint against services/vision/runtime/weights.sha256 before loading.
exec python -m services.vision.sam_worker --preload

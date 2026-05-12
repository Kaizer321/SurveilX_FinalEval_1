#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/app"
MODELPATH="${VIOLENCE_CKPT_PATH:-}"
MODEL_URL="${MODEL_URL:-}"

# If a MODEL_URL is supplied and model path not present, download it
if [[ -n "$MODEL_URL" && -n "$MODELPATH" ]]; then
  if [[ ! -f "$MODELPATH" ]]; then
    echo "Model not found at $MODELPATH. Downloading from $MODEL_URL..."
    mkdir -p "$(dirname "$MODELPATH")"
    if command -v curl >/dev/null 2>&1; then
      curl -L "$MODEL_URL" -o "$MODELPATH"
    elif command -v wget >/dev/null 2>&1; then
      wget -O "$MODELPATH" "$MODEL_URL"
    else
      echo "No curl or wget available to download model. Exiting." >&2
      exit 1
    fi
    echo "Download complete."
  else
    echo "Model already present at $MODELPATH"
  fi
fi

# If model path is set but file missing and no MODEL_URL, warn and continue (app falls back to demo)
if [[ -n "$MODELPATH" && ! -f "$MODELPATH" ]]; then
  echo "Warning: VIOLENCE_CKPT_PATH set to $MODELPATH but file not found. App will run in demo mode." >&2
fi

# Run database migrations or initialization if needed (no-op placeholder)
# e.g., python -m src.metadata.migrations upgrade head

# Start Uvicorn
exec uvicorn app:app --host 0.0.0.0 --port 8000

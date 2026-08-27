#!/usr/bin/env bash
# Shared launch logic for serve_qwen_coder.sh / serve_phi4mini.sh. Not meant to
# be run directly - sourced by those scripts, which set MODEL_LABEL,
# DEFAULT_MODEL_FILE, and PORT before sourcing this file.
set -euo pipefail

LLAMA_SERVER="$SCRIPT_DIR/bin/llama-server"
MODEL_FILE="${LLAMA_MODEL_FILE:-$DEFAULT_MODEL_FILE}"
CTX_SIZE="${LLAMA_CTX_SIZE:-4096}"
NGL="${LLAMA_NGL:-99}"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  echo "llama-server not found at $LLAMA_SERVER - run local-llm/install_llama_server.sh first." >&2
  exit 1
fi
if [[ ! -f "$MODEL_FILE" ]]; then
  echo "Model file not found: $MODEL_FILE - run local-llm/download_models.sh first (or set LLAMA_MODEL_FILE to an alternate quant)." >&2
  exit 1
fi

# GPU offload confirmation is done via nvidia-smi memory usage, not by
# grepping llama-server's own log: verified live against a real server that
# at this build's default verbosity, no "offload"/"vulkan"/"cuda"/"gpu" text
# is printed at all - the log alone can't tell you whether it worked.
GPU_BASELINE_MIB=""
if command -v nvidia-smi >/dev/null; then
  GPU_BASELINE_MIB="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1)"
fi

echo "Starting $MODEL_LABEL on port $PORT (ngl=$NGL, ctx=$CTX_SIZE)..."
LOG_FILE="$(mktemp)"
trap 'rm -f "$LOG_FILE"' EXIT

"$LLAMA_SERVER" -m "$MODEL_FILE" --port "$PORT" -ngl "$NGL" -c "$CTX_SIZE" --host 127.0.0.1 2>&1 | tee "$LOG_FILE" &
SERVER_PID=$!

# Poll for the server actually accepting connections (or a clear failure),
# then check whether GPU memory usage actually grew.
READY=0
for _ in $(seq 1 60); do
  sleep 1
  if grep -qiE "error|failed to (load|allocate)" "$LOG_FILE" 2>/dev/null; then
    echo "WARNING: llama-server logged an error during startup - check the output above." >&2
    break
  fi
  if grep -qiE "listening on|server is listening" "$LOG_FILE" 2>/dev/null; then
    READY=1
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "WARNING: llama-server exited during startup - check the output above." >&2
    break
  fi
done

if [[ "$READY" == "1" ]]; then
  if [[ -n "$GPU_BASELINE_MIB" ]]; then
    GPU_NOW_MIB="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1)"
    GPU_DELTA=$(( GPU_NOW_MIB - GPU_BASELINE_MIB ))
    if (( GPU_DELTA > 200 )); then
      echo "GPU offload confirmed - GPU memory usage grew by ${GPU_DELTA}MiB (now ${GPU_NOW_MIB}MiB)."
    else
      echo "WARNING: GPU memory usage barely changed (+${GPU_DELTA}MiB) - this may be running on CPU only. Check -ngl and that Vulkan drivers are working (see README.md)." >&2
    fi
  else
    echo "NOTE: nvidia-smi not found - can't automatically confirm GPU offload. Server is up; check its own resource usage manually if unsure."
  fi
else
  echo "WARNING: could not confirm the server reached a ready state within the timeout - check the output above." >&2
fi

wait "$SERVER_PID"

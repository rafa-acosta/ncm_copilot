#!/usr/bin/env bash
# Shared launch logic for serve_qwen_coder.sh / serve_phi4mini.sh. Not meant to
# be run directly - sourced by those scripts, which set MODEL_LABEL,
# DEFAULT_MODEL_FILE, and PORT before sourcing this file.
set -euo pipefail

LLAMA_SERVER="$SCRIPT_DIR/bin/llama-server"
MODEL_FILE="${LLAMA_MODEL_FILE:-$DEFAULT_MODEL_FILE}"
CTX_SIZE="${LLAMA_CTX_SIZE:-2048}"
NGL="${LLAMA_NGL:-99}"

# This build defaults to `-np -1` (auto slot count) and an 8192MiB
# `--cache-ram` idle-slot cache that RETAINS each slot's KV state instead of
# freeing it (see `llama-server --help`'s --cache-idle-slots: "default:
# enabled, requires cache-ram"). Every call this project makes is a single,
# unrelated one-shot prompt (a different device/finding each time) - there is
# no prefix to reuse, so that cache never helps and only accumulates, which
# is exactly the "RAM climbs steadily over hundreds of requests until OOM"
# failure mode. Force a single slot and disable the idle-slot cache instead.
NP="${LLAMA_NP:-1}"
CACHE_RAM="${LLAMA_CACHE_RAM:-0}"

# Hard ceiling so a leak (this one, or a future/different one) gets this
# process OOM-killed at a safe, contained limit instead of the whole system
# running out of RAM. Paired with the restart loop below so hitting the
# ceiling costs a reload, not the rest of the batch. Requires systemd --user;
# falls back to no ceiling (with a warning) if unavailable.
MEM_MAX="${LLAMA_MEM_MAX:-8G}"
MAX_RESTARTS="${LLAMA_MAX_RESTARTS:-5}"
RESTART_COOLDOWN="${LLAMA_RESTART_COOLDOWN:-5}"

if [[ ! -x "$LLAMA_SERVER" ]]; then
  echo "llama-server not found at $LLAMA_SERVER - run local-llm/install_llama_server.sh first." >&2
  exit 1
fi
if [[ ! -f "$MODEL_FILE" ]]; then
  echo "Model file not found: $MODEL_FILE - run local-llm/download_models.sh first (or set LLAMA_MODEL_FILE to an alternate quant)." >&2
  exit 1
fi

SYSTEMD_RUN=""
if command -v systemd-run >/dev/null 2>&1; then
  SYSTEMD_RUN="$(command -v systemd-run)"
else
  echo "NOTE: systemd-run not found - launching without a memory ceiling (LLAMA_MEM_MAX=$MEM_MAX won't be enforced)." >&2
fi

EXEC_ARGS=("$LLAMA_SERVER" -m "$MODEL_FILE" --port "$PORT" -ngl "$NGL" -c "$CTX_SIZE" \
  --parallel "$NP" --cache-ram "$CACHE_RAM" --no-cache-idle-slots --host 127.0.0.1)

# GPU offload confirmation is done via nvidia-smi memory usage, not by
# grepping llama-server's own log: verified live against a real server that
# at this build's default verbosity, no "offload"/"vulkan"/"cuda"/"gpu" text
# is printed at all - the log alone can't tell you whether it worked.
GPU_BASELINE_MIB=""
if command -v nvidia-smi >/dev/null; then
  GPU_BASELINE_MIB="$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1)"
fi

# Supervisor loop: if the server ever exits - whether OOM-killed by the
# MemoryMax ceiling above, an upstream crash, or anything else - relaunch it
# automatically (up to LLAMA_MAX_RESTARTS times) instead of taking the whole
# batch down. llm_client.py's retry logic rides out the reload window on the
# client side, so a batch run pays a delay here, not a lost run.
RESTART_COUNT=0
while true; do
  LOG_FILE="$(mktemp)"
  trap 'rm -f "$LOG_FILE"' EXIT

  echo "Starting $MODEL_LABEL on port $PORT (ngl=$NGL, ctx=$CTX_SIZE, np=$NP, cache-ram=${CACHE_RAM}MiB, mem-max=${SYSTEMD_RUN:+$MEM_MAX}${SYSTEMD_RUN:-none}) [attempt $((RESTART_COUNT + 1))/$((MAX_RESTARTS + 1))]..."

  if [[ -n "$SYSTEMD_RUN" ]]; then
    "$SYSTEMD_RUN" --user --scope --collect -p "MemoryMax=$MEM_MAX" -p MemorySwapMax=0 -- "${EXEC_ARGS[@]}" 2>&1 | tee "$LOG_FILE" &
  else
    "${EXEC_ARGS[@]}" 2>&1 | tee "$LOG_FILE" &
  fi
  SERVER_PID=$!

  # Poll for the server actually accepting connections (or a clear failure),
  # then check whether GPU memory usage actually grew. Default timeout is
  # generous (3 min) because a cold disk cache can make the larger model
  # (Qwen2.5-Coder-7B, ~4.7GB) take over a minute to load - a tighter window
  # produced a spurious "not ready" warning for a server that came up fine
  # moments later. Override with LLAMA_READY_TIMEOUT if your disk is slower still.
  READY=0
  for _ in $(seq 1 "${LLAMA_READY_TIMEOUT:-180}"); do
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

  EXIT_CODE=0
  wait "$SERVER_PID" || EXIT_CODE=$?
  rm -f "$LOG_FILE"

  if (( RESTART_COUNT >= MAX_RESTARTS )); then
    echo "llama-server has exited $((RESTART_COUNT + 1)) time(s) (last exit code $EXIT_CODE) - giving up after LLAMA_MAX_RESTARTS=$MAX_RESTARTS automatic restarts. Check logs above; consider lowering LLAMA_CTX_SIZE or LLAMA_MEM_MAX further." >&2
    exit 1
  fi
  RESTART_COUNT=$((RESTART_COUNT + 1))
  echo "llama-server exited (code $EXIT_CODE) - this is expected if the LLAMA_MEM_MAX=$MEM_MAX ceiling was hit. Restarting in ${RESTART_COOLDOWN}s (attempt $((RESTART_COUNT + 1))/$((MAX_RESTARTS + 1)))..." >&2
  sleep "$RESTART_COOLDOWN"
done

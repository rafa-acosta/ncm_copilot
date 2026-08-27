#!/usr/bin/env bash
# Launches llama-server for Phi-4-mini-instruct - the "fast_default" backend in
# config.yaml (quick iteration, low latency) - on port 8081.
#
# Prerequisites: ./install_llama_server.sh and ./download_models.sh
#
# Reference command (see LOCAL_LLM_SETUP_PROMPT.md):
#   llama-server -m ./models/phi-4-mini-instruct-q4_k_m.gguf --port 8081 -ngl 99 -c 4096 --host 127.0.0.1
#
# Override without editing this file (see README.md's VRAM fallback ladder):
#   LLAMA_MODEL_FILE=path/to/other.gguf   e.g. the smaller Q3_K_M quant
#   LLAMA_CTX_SIZE=2048                   reduce context if VRAM is tight
#   LLAMA_NGL=20                          partial GPU offload instead of full (-ngl 99)
#
# Reminder: only one of serve_qwen_coder.sh / serve_phi4mini.sh is expected to
# run at a time on 6GB VRAM hardware (~4.7GB + ~2.3GB would exceed it).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_LABEL="Phi-4-mini-instruct"
DEFAULT_MODEL_FILE="$SCRIPT_DIR/models/phi-4-mini-instruct-q4_k_m.gguf"
PORT=8081

# shellcheck source=./_serve_common.sh
source "$SCRIPT_DIR/_serve_common.sh"

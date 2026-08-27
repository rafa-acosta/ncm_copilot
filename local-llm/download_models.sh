#!/usr/bin/env bash
# Downloads both GGUF models used by serve_qwen_coder.sh / serve_phi4mini.sh
# into local-llm/models/. Requires the `hf` CLI (part of huggingface_hub, in
# this repo's requirements.txt - `huggingface-cli` is its deprecated
# predecessor name; this script uses `hf` if present and falls back to
# `huggingface-cli` for older huggingface_hub installs).
#
# Pre-quantized GGUF repos are used directly - no manual conversion step -
# verified live against the Hugging Face API before writing this script:
#   - Phi-4-mini-instruct: unsloth/Phi-4-mini-instruct-GGUF (Microsoft doesn't
#     publish GGUF themselves for this model; unsloth is the highest-trust
#     community quantizer available, 76.9k downloads at time of writing)
#   - Qwen2.5-Coder-7B-Instruct: Qwen/Qwen2.5-Coder-7B-Instruct-GGUF - the
#     OFFICIAL Qwen org, most trustworthy source possible
# If either repo/file ever disappears or is renamed, the fallback path is
# llama.cpp's convert_hf_to_gguf.py + llama-quantize <model>-f16.gguf
# <model>-Q4_K_M.gguf Q4_K_M - see README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="$SCRIPT_DIR/models"
mkdir -p "$MODELS_DIR"

if command -v hf >/dev/null; then
  HF_DOWNLOAD=(hf download)
elif command -v huggingface-cli >/dev/null; then
  HF_DOWNLOAD=(huggingface-cli download)
else
  echo "Neither 'hf' nor 'huggingface-cli' found. Install with: pip install huggingface_hub (already in requirements.txt - run: pip install -r requirements.txt)" >&2
  exit 1
fi

# Args: HF repo, filename on the Hub, local filename to save as, expected byte
# size (a sanity check against a truncated/failed download, not a checksum -
# sizes verified live against the Hub before writing this script; a small
# tolerance is allowed in case a repo re-quantizes with a slightly different size).
download() {
  local repo="$1" hub_file="$2" local_name="$3" expected_bytes="$4"
  local out="$MODELS_DIR/$local_name"

  if [[ -f "$out" ]]; then
    local existing_size
    existing_size=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
    if (( existing_size >= expected_bytes * 95 / 100 )); then
      echo "Already present: $out ($existing_size bytes)"
      return
    fi
    echo "Existing $out looks incomplete ($existing_size bytes) - re-downloading."
    rm -f "$out"
  fi

  echo "Downloading $repo / $hub_file ..."
  "${HF_DOWNLOAD[@]}" "$repo" "$hub_file" --local-dir "$MODELS_DIR"
  mv "$MODELS_DIR/$hub_file" "$out"

  local size
  size=$(stat -c%s "$out" 2>/dev/null || stat -f%z "$out")
  if (( size < expected_bytes * 90 / 100 )); then
    echo "ERROR: $out is only $size bytes (expected roughly $expected_bytes) - looks like a failed or partial download." >&2
    exit 1
  fi
  echo "OK: $out ($size bytes)"
}

download "unsloth/Phi-4-mini-instruct-GGUF" "Phi-4-mini-instruct-Q4_K_M.gguf" \
  "phi-4-mini-instruct-q4_k_m.gguf" 2491874272

download "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF" "qwen2.5-coder-7b-instruct-q4_k_m.gguf" \
  "qwen2.5-coder-7b-instruct-q4_k_m.gguf" 4683073536

echo
echo "All models present in $MODELS_DIR"
echo "Start one with: ./serve_qwen_coder.sh   or   ./serve_phi4mini.sh"
echo "(only one at a time - see README.md's VRAM budget)"

#!/usr/bin/env bash
# Downloads a prebuilt llama.cpp release into local-llm/bin/ - no compiler
# needed (this machine has no gcc/cmake/make). Not part of the original
# local-llm spec's file list; added because nothing else provides the
# `llama-server` binary the serve_*.sh scripts need. See
# LOCAL_LLM_SETUP_PROMPT.md's Implementation Notes for why this targets the
# Vulkan build rather than CUDA: llama.cpp's GitHub releases only ship a
# prebuilt CUDA binary for Windows, not Linux. Vulkan is Linux's no-compile
# GPU path instead, and NVIDIA GPUs support it via the driver's own Vulkan
# ICD (no CUDA toolkit required) - confirmed present on this machine.
#
# Safe to re-run: does nothing if local-llm/bin/llama-server already exists.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$SCRIPT_DIR/bin"
REPO="ggml-org/llama.cpp"

mkdir -p "$BIN_DIR"

if [[ -x "$BIN_DIR/llama-server" ]]; then
  echo "Already installed: $BIN_DIR/llama-server"
  "$BIN_DIR/llama-server" --version || true
  exit 0
fi

command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
command -v tar >/dev/null || { echo "tar is required." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (used to parse the GitHub API response)." >&2; exit 1; }

echo "Looking up the latest numbered llama.cpp release..."
# The literal "latest" GitHub release for this repo carries no binary assets
# (it's a rolling nightly-tag marker, verified before writing this script) -
# the real numbered build releases (tag bNNNNN) do.
TAG="$(curl -fsSL "https://api.github.com/repos/$REPO/releases?per_page=1" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['tag_name'])")"
echo "Latest build: $TAG"

ASSET="llama-${TAG}-bin-ubuntu-vulkan-x64.tar.gz"
URL="https://github.com/$REPO/releases/download/$TAG/$ASSET"
ARCHIVE="$BIN_DIR/$ASSET"

echo "Downloading $URL"
curl -fL --progress-bar -o "$ARCHIVE" "$URL"

EXTRACT_DIR="$BIN_DIR/${TAG}-vulkan-x64"
mkdir -p "$EXTRACT_DIR"
tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
rm -f "$ARCHIVE"

# Don't assume the tarball's internal layout - it has changed across
# llama.cpp releases before. Find the real binary instead of hardcoding a path.
FOUND="$(find "$EXTRACT_DIR" -type f -name "llama-server" | head -n1)"
if [[ -z "$FOUND" ]]; then
  echo "ERROR: llama-server binary not found inside $ASSET after extraction." >&2
  echo "The release asset naming may have changed - check https://github.com/$REPO/releases/tag/$TAG manually." >&2
  exit 1
fi
chmod +x "$FOUND"
ln -sf "$FOUND" "$BIN_DIR/llama-server"

echo "Installed: $BIN_DIR/llama-server -> $FOUND"
"$BIN_DIR/llama-server" --version || echo "WARNING: 'llama-server --version' failed - check that Vulkan runtime libraries (libvulkan1) are installed. See README.md."

# Local LLM Setup

Local model backend for the Compliance Remediation Advisor (`vibecoding_advise.py` /
`COMPLIANCE_ANALYZER_PROMPT.md`). Two models, both served via `llama.cpp`, on two ports.
See `LOCAL_LLM_SETUP_PROMPT.md` for the original spec and design rationale.

## Why llama.cpp, and why Vulkan not CUDA

Target hardware: **NVIDIA RTX 4050, 6GB GDDR6 VRAM.** vLLM's memory-reservation model
and lack of graceful CPU/GPU offload make it a poor fit for a 6GB card — llama.cpp with
full GPU offload (`-ngl 99`) is the right tool here.

llama.cpp's official GitHub releases only ship a **prebuilt CUDA binary for Windows** —
Linux gets no CUDA build at all without compiling from source (and this machine has no
gcc/cmake/make). The no-compile GPU path on Linux is the **Vulkan** build instead
(`llama-b<N>-bin-ubuntu-vulkan-x64.tar.gz`). NVIDIA GPUs support GPU compute via Vulkan
through the driver's own Vulkan ICD — no CUDA toolkit required. `install_llama_server.sh`
fetches this build; `-ngl` (GPU layer offload) works identically through it.

## VRAM budget — only one model at a time

| Model | Role | Quant | Approx. VRAM |
|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct | `specialist` | Q4_K_M | ~4.5–4.8 GB |
| Phi-4-mini-instruct | `fast_default` | Q4_K_M | ~2.2–2.5 GB |

**Do not run both at once.** Combined (~7GB) exceeds 6GB even before OS/display overhead.
`serve_qwen_coder.sh` and `serve_phi4mini.sh` each start exactly one server; nothing here
starts both by default. `vibecoding_advise.py --backend auto` already handles this
gracefully — it pings every backend in `config.yaml` and uses whichever one is actually
running.

## Setup, in order

```bash
cd local-llm
./install_llama_server.sh      # fetches the prebuilt llama-server binary into ./bin/ (~15MB)
./download_models.sh           # fetches both GGUFs into ./models/ (~6.7GB total, ~7GB free disk needed)

./serve_qwen_coder.sh          # OR ./serve_phi4mini.sh - pick one, run in its own terminal
```

In another terminal, once a server is up:

```bash
python healthcheck.py                                    # confirm it's reachable
cd ..
python vibecoding_advise.py --report reports/report.json --controls controls.yaml \
    --backend auto --output-md briefing.md --output-json briefing.json
```

`--backend auto` picks `specialist` (Qwen) for a single-device report and `fast_default`
(Phi-4-mini) when briefing many devices at once (see `llm_client.select_backend`) — or
target one directly with `--backend qwen_coder` / `--backend phi4_mini`.

## If a model fails to load (out-of-memory)

Each `serve_*.sh` script honors three environment variables, so none of this needs
editing the scripts:

```bash
# 1. Reduce context first - cheapest fix, no re-download needed
LLAMA_CTX_SIZE=2048 ./serve_qwen_coder.sh

# 2. Drop to a smaller quantization - both repos publish Q3_K_M (smaller than
#    Q4_K_M; neither repo actually has a Q4_K_S build, despite what you might
#    see suggested elsewhere - verified against the real file listing)
hf download Qwen/Qwen2.5-Coder-7B-Instruct-GGUF qwen2.5-coder-7b-instruct-q3_k_m.gguf --local-dir models
LLAMA_MODEL_FILE=./models/qwen2.5-coder-7b-instruct-q3_k_m.gguf ./serve_qwen_coder.sh

# 3. Partial GPU offload as a last resort (slower - some layers run on CPU/RAM)
LLAMA_NGL=20 ./serve_qwen_coder.sh
```

Combine as needed, e.g. `LLAMA_CTX_SIZE=2048 LLAMA_NGL=20 ./serve_qwen_coder.sh`.

## Files

- `install_llama_server.sh` — fetches the `llama-server` binary (Vulkan Linux build) into `bin/`. Not in the original spec's file list — added because nothing else here provides the binary itself.
- `download_models.sh` — fetches both GGUFs into `models/`, with size-sanity checks.
- `serve_qwen_coder.sh` / `serve_phi4mini.sh` — launch one server each; share their startup/GPU-offload-detection logic via `_serve_common.sh`.
- `config.yaml` — the backend registry `llm_client.py` reads directly.
- `healthcheck.py` — pings both endpoints, exits nonzero if neither is up.

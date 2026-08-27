# VibeCoding — Local LLM Setup (Phi-4-mini + Qwen2.5-Coder-7B) — Claude Code Build Prompt

## Context

This sets up the local LLM backend that the **Compliance Remediation Advisor (CRA)** tool (see `COMPLIANCE_ANALYZER_PROMPT.md`) connects to. Target hardware: a laptop with an **NVIDIA RTX 4050 (6GB GDDR6 VRAM)**. Given the VRAM ceiling, the backend engine is **llama.cpp**, not vLLM — vLLM's memory reservation model and lack of graceful CPU/GPU offload make it a poor fit for a 6GB card; llama.cpp with full GPU offload (`-ngl 99`) is the right tool here.

Two models are needed, serving different roles:

| Model | Role | Quantization | Approx. VRAM |
|---|---|---|---|
| **Phi-4-mini-instruct** | Fast/default model — quick iteration, low latency, comfortable headroom on 6GB | Q4_K_M GGUF | ~2.2–2.5 GB |
| **Qwen2.5-Coder-7B-Instruct** | Primary "specialist" model for Cisco IOS-XE syntax synthesis — better structured-syntax handling | Q4_K_M GGUF | ~4.5–4.8 GB |

Both must run via `llama-server` (OpenAI-compatible endpoint), selectable through the existing `--backend` / config mechanism in the CRA tool — this setup should expose them as two distinct named endpoints/ports so the CRA can point at whichever is running.

---

## Goal

Produce scripts and config (not one-off manual commands) under a new `local-llm/` directory in the VibeCoding project:

1. `local-llm/download_models.sh` — downloads both models from Hugging Face in GGUF format (prefer pre-quantized GGUF repos if available and trustworthy — e.g. community GGUF conversions — to avoid a manual conversion step; fall back to `llama.cpp`'s `convert_hf_to_gguf.py` + `llama-quantize` if a pre-quantized Q4_K_M isn't available).
2. `local-llm/serve_phi4mini.sh` — launches `llama-server` for Phi-4-mini-instruct.
3. `local-llm/serve_qwen_coder.sh` — launches `llama-server` for Qwen2.5-Coder-7B-Instruct.
4. `local-llm/config.yaml` — declares both endpoints (name, base_url, port, role) in a format the CRA tool's backend-selection logic can read directly.
5. `local-llm/healthcheck.py` — small script that pings both `/v1/models` endpoints and reports which are up, matching the health-check behavior already expected by the CRA tool's `--backend auto` logic.
6. A short `local-llm/README.md` explaining VRAM budget, why llama.cpp over vLLM on this hardware, and how to fall back to smaller quantization (Q4_K_S) or reduced context if VRAM runs out.

---

## Model & Quantization Details

### Phi-4-mini-instruct
- Source: Microsoft's Phi-4-mini-instruct on Hugging Face.
- Target quant: **Q4_K_M** (GGUF). If no pre-quantized GGUF repo is trustworthy/available, convert from the original safetensors using `llama.cpp`'s `convert_hf_to_gguf.py`, then quantize with `llama-quantize <model>-f16.gguf <model>-Q4_K_M.gguf Q4_K_M`.
- Launch target: port **8081**.
- Context: 4096 tokens (plenty of headroom on 6GB alongside the Qwen model if run sequentially, not concurrently — see note below).

### Qwen2.5-Coder-7B-Instruct
- Source: Qwen's Qwen2.5-Coder-7B-Instruct on Hugging Face.
- Target quant: **Q4_K_M** (GGUF). Same conversion path as above if a pre-quantized version isn't available.
- Launch target: port **8080**.
- Context: 4096 tokens. If VRAM pressure appears (other processes competing for the 6GB pool), the script should support an easy override to drop to **Q4_K_S** or context 2048 via a flag or env var — document this clearly, don't hardcode a single failure mode.

### Important VRAM constraint
Both models should NOT be assumed to run **simultaneously** on this 6GB card — running both at once (Phi-4-mini ~2.3GB + Qwen-Coder ~4.7GB = ~7GB) will likely exceed available VRAM once OS/display overhead is accounted for. The launch scripts and `config.yaml` should support **starting either one on demand**, not both by default. Document this explicitly in the README so the operator (and the CRA tool's `--backend auto` logic) knows only one is expected to be live at a time on this hardware profile — the "auto-detect whichever's running" logic from `COMPLIANCE_ANALYZER_PROMPT.md` already handles this gracefully.

---

## `llama-server` Launch Command Reference (embed as reference/comments in the scripts)

```bash
# Qwen2.5-Coder-7B-Instruct (primary specialist model)
llama-server \
  -m ./models/qwen2.5-coder-7b-instruct-q4_k_m.gguf \
  --port 8080 \
  -ngl 99 \
  -c 4096 \
  --host 127.0.0.1

# Phi-4-mini-instruct (fast/default model)
llama-server \
  -m ./models/phi-4-mini-instruct-q4_k_m.gguf \
  --port 8081 \
  -ngl 99 \
  -c 4096 \
  --host 127.0.0.1
```

`-ngl 99` forces all layers onto GPU (safe for both models at Q4_K_M on 6GB, run one at a time). If VRAM errors occur, the fallback documented in the README is to reduce `-ngl` (partial CPU offload) before dropping quantization further.

---

## `config.yaml` Schema (for CRA tool integration)

```yaml
backends:
  qwen_coder:
    role: specialist
    base_url: http://127.0.0.1:8080/v1
    model_name: qwen2.5-coder-7b-instruct-q4_k_m
  phi4_mini:
    role: fast_default
    base_url: http://127.0.0.1:8081/v1
    model_name: phi-4-mini-instruct-q4_k_m
notes: >
  Only one backend is expected to be running at a time on 6GB VRAM hardware.
  The CRA tool's --backend auto logic pings both base_urls and uses whichever
  responds; explicit --backend flag can target either by name.
```

---

## Acceptance Criteria

1. `download_models.sh` fetches both models without requiring manual Hugging Face UI interaction (uses `huggingface-cli download` or equivalent); checksums or file-size sanity checks included to catch failed/partial downloads.
2. Both `serve_*.sh` scripts start cleanly on a fresh RTX 4050 (6GB) laptop with correct `-ngl`/context defaults, and print a clear log line confirming GPU offload succeeded (not silently falling back to CPU).
3. `healthcheck.py` correctly reports up/down status for both endpoints and exits with a non-zero code if neither is reachable, mirroring the error behavior specified in `COMPLIANCE_ANALYZER_PROMPT.md`.
4. `config.yaml` is directly consumable by the CRA tool's backend-selection code — no format mismatch between this file and what `vibecoding-advise` expects.
5. README explicitly documents the "one model at a time" VRAM constraint and gives the exact fallback steps (reduce quant, reduce context, reduce `-ngl`) if a load fails with an out-of-memory error.
6. No hardcoded absolute paths — scripts work relative to the `local-llm/` directory regardless of where the VibeCoding project is cloned.

## Implementation Notes (this build)

- **Backend selection was generalized**, not kept as the literal vLLM-vs-llama.cpp binary choice from `COMPLIANCE_ANALYZER_PROMPT.md`: `llm_client.py`'s `select_backend`/`LLMClient`/`vibecoding_advise.py --backend` now work off a named registry loaded from this directory's `config.yaml` (`qwen_coder`, `phi4_mini`, or any future entry), not a fixed `vllm`/`llamacpp` engine-type enum. Decided with the user before implementation, since two *models* on one *engine* is what this hardware actually needs, not two *engines*. The repo-root `config.yaml` (flat `vllm_url`/`llamacpp_url`) from the CRA build is retired; `local-llm/config.yaml` is now the single source of truth the CRA reads.
- **`install_llama_server.sh` was added**, beyond this prompt's literal file list: nothing here provides the `llama-server` binary itself, and this machine has no compiler (no gcc/cmake/make) to build it from source.
- **The no-compile GPU path on Linux is Vulkan, not CUDA**: llama.cpp's official GitHub releases (`ggml-org/llama.cpp`) only ship a prebuilt CUDA binary for Windows — Linux's no-compile GPU option is the `*-bin-ubuntu-vulkan-x64.tar.gz` release asset. This machine already has a working NVIDIA Vulkan ICD installed (confirmed via `/usr/share/vulkan/icd.d/nvidia_icd.json`, `libvulkan1`, `libnvidia-gl-595`), so `-ngl` GPU-layer offload works the same way through Vulkan as it would through CUDA, with no additional driver/toolkit install needed.
- **Model sources, verified live against Hugging Face (metadata only, no weights fetched) before writing `download_models.sh`**:
  - Phi-4-mini-instruct Q4_K_M: `unsloth/Phi-4-mini-instruct-GGUF` / `Phi-4-mini-instruct-Q4_K_M.gguf` (2,491,874,272 bytes). Microsoft doesn't publish GGUF themselves for this model; unsloth is the highest-trust community quantizer available (76.9k downloads at time of writing).
  - Qwen2.5-Coder-7B-Instruct Q4_K_M: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` — the official Qwen org — / `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, the single consolidated file rather than the split multi-part variant (4,683,073,536 bytes).
- **The README's fallback quantization is Q3_K_M, not Q4_K_S**: neither GGUF repo above actually publishes a Q4_K_S file (verified against the real file listing); Q3_K_M exists in both and is what's documented as the smaller-footprint fallback instead.
- Scripts and config were built and verified for correctness (syntax-checked, schema round-tripped, tests updated) without actually executing the multi-GB downloads — the operator runs `install_llama_server.sh` then `download_models.sh` when ready. See `local-llm/README.md` for the exact run order.

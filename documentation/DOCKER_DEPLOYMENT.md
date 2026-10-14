# Docker Deployment Guide

Portable, GPU-enabled deployment of NCM Copilot (web app + local LLM engine)
to a client's Linux server, as two containers under Docker Compose. This is
the deployment path for a technical operator with server/SSH access - not a
double-click installer for an end user's own laptop.

Two services:

- **webapp** - this repo's FastAPI backend + static frontend, built from
  `docker/Dockerfile.webapp`.
- **llm-engine** - the stock, official `ghcr.io/ggml-org/llama.cpp:server-cuda`
  image (no custom build), running one GGUF model with GPU acceleration.

They talk to each other over Docker's internal compose network
(`http://llm-engine:8080/v1`) - nothing here depends on the host's own
network configuration beyond the one port you expose for the browser.

---

## 1. Prerequisites (client server, one-time)

**Docker Engine + the Compose plugin:**

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
docker compose version   # confirms the compose PLUGIN is present, not the
                          # older standalone `docker-compose` binary
```

**NVIDIA driver** (if not already installed) - confirm first:

```bash
nvidia-smi   # must already show your GPU before continuing
```

**NVIDIA Container Toolkit** (lets Docker containers access the GPU):

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**Verify GPU passthrough works before touching this project at all** - this
isolates "GPU passthrough is broken" from "the app is broken" if something
goes wrong later:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

If that doesn't print your GPU, stop here and fix it first - nothing below
will work without it.

---

## 2. Clone the repo

```bash
git clone <this repo's URL> ncm_copilot
cd ncm_copilot/docker
```

Everything from here on is run from inside `docker/`.

---

## 3. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and confirm/adjust:

- `LLM_MODEL_FILE` / `LLM_MODEL_NAME` - which model to run. Phi-4-mini
  (the default) needs less VRAM and is faster for batch briefings;
  Qwen2.5-Coder-7B is the "specialist" model with better structured
  Cisco IOS-XE handling but needs more VRAM. Only one runs at a time - see
  the comments in `.env.example`.
- `WEBAPP_PORT` - which host port the browser UI listens on (default 8000).

---

## 4. Download the model

Into `docker/models/` (matches `LLM_MODEL_FILE` above). Requires the
project's Python environment (`pip install -r ../requirements.txt`) for the
`hf` CLI, or install `huggingface_hub` standalone.

```bash
# Phi-4-mini-instruct (default - ~2.5GB)
hf download unsloth/Phi-4-mini-instruct-GGUF Phi-4-mini-instruct-Q4_K_M.gguf \
  --local-dir models
mv models/Phi-4-mini-instruct-Q4_K_M.gguf models/phi-4-mini-instruct-q4_k_m.gguf

# OR Qwen2.5-Coder-7B-Instruct (~4.7GB) - only if you set LLM_MODEL_FILE to it
hf download Qwen/Qwen2.5-Coder-7B-Instruct-GGUF qwen2.5-coder-7b-instruct-q4_k_m.gguf \
  --local-dir models
```

(Same source repos `local-llm/download_models.sh` uses for the bare-metal
setup - see that script's comments for provenance/trust notes.)

---

## 5. Start everything

```bash
docker compose up --build -d
```

First run pulls/builds images and can take a few minutes (the CUDA base
image and the model loading are the slow parts). Watch progress with:

```bash
docker compose logs -f
```

---

## 6. Verify

1. Open `http://<server-ip>:8000` (or whatever `WEBAPP_PORT` you set) in a
   browser.
2. Go to **Settings**. The LLM backend should show as **Online**, with no
   Start/Stop buttons and a "started outside this app" note - that's
   correct and expected: the engine is a separate container, managed by
   `docker compose`, not a process the webapp spawns itself.
3. Upload a config under **Configuration Files**, run an **Analysis**,
   then generate a **Briefing** for it - this confirms the webapp
   container can actually reach and complete a real request against the
   llm-engine container, not just a reachability ping.

---

## 7. Day-2 operations

| Task | Command |
|---|---|
| View logs | `docker compose logs -f [webapp\|llm-engine]` |
| Restart after an `.env` model swap | `docker compose up -d --build llm-engine` |
| Stop (data persists) | `docker compose down` |
| Stop and wipe all data | `docker compose down -v` (destroys the `ncm_data` volume - uploaded configs, Golden Config profiles, analysis runs) |
| Update to a new version | `git pull && docker compose up --build -d` |

Data (`webapp/data/` equivalent) lives in the named Docker volume
`ncm_data`, not in the repo checkout - it survives `docker compose down`,
rebuilds, and `git pull` updates. Only `docker compose down -v` removes it.

---

## Appendix: offline / air-gapped transfer

If the client server has no internet access, build everything on a machine
that does, then transfer:

```bash
# On your machine, after `docker compose build`:
docker save ncm_copilot-webapp ghcr.io/ggml-org/llama.cpp:server-cuda -o ncm-copilot-images.tar

# Copy ncm-copilot-images.tar AND docker/models/*.gguf to the client server
# (USB drive, internal file share, etc.), then on the client server:
docker load -i ncm-copilot-images.tar
docker compose up -d   # no --build needed - images are already loaded
```

The NVIDIA driver + Container Toolkit installation in Section 1 still needs
whatever offline package mirror your environment normally uses - that part
isn't specific to this project.

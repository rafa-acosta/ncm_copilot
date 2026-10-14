#!/usr/bin/env bash
# Renders docker/config.docker.yaml.template -> the path
# AGENT_ASSISTED_CODING_LLM_CONFIG points at (see Dockerfile.webapp), filling
# in LLM_MODEL_NAME from the environment (set via docker/.env, passed through
# by docker-compose.yml) so the briefing/report metadata's displayed model
# name stays accurate when the user swaps LLM_MODEL between phi4_mini and
# qwen_coder - without needing any change to llm_client.py's own
# AGENT_ASSISTED_CODING_LLM_CONFIG / load_backends_registry() mechanism.
set -euo pipefail

: "${LLM_MODEL_NAME:?LLM_MODEL_NAME must be set - see docker/.env.example}"

envsubst '${LLM_MODEL_NAME}' \
  < /app/docker/config.docker.yaml.template \
  > /app/docker/config.docker.yaml

exec python3 -m uvicorn webapp.backend.app:app --host 0.0.0.0 --port 8000

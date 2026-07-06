#!/usr/bin/env bash
# Serve Ornith-1.0-35B (sparse MoE, ~3B active/token) on an RTX 3070 (8GB) + 64GB RAM
# via llama.cpp expert-offload: the 256 routed experts live in system RAM, the active
# path + KV cache stay on the GPU. Exposes an OpenAI-compatible API at localhost:${PORT}/v1
#
# This is the "non-obvious win" — it runs a 21.2GB model on an 8GB card. Expect ~15-40 tok/s
# on DDR4 (older CPU pulls toward the low end). See docs/serving.md and docs/hardware.md.
#
# Prereq: llama.cpp built with CUDA. NOTE: Ollama CANNOT do this (no --n-cpu-moe). Use llama.cpp.
#
# Usage:  ./serve-35b.sh                  # defaults: Q4_K_M, 32K ctx, port 8000
#         PORT=8002 CTX=65536 ./serve-35b.sh
set -euo pipefail

LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
QUANT="${QUANT:-Q4_K_M}"      # Q4_K_M = 21.2GB; fits in 64GB RAM with room to spare
CTX="${CTX:-32768}"           # 32K default. Do NOT set 262144 on 8GB (KV alone ~10.7GB).
PORT="${PORT:-8000}"
NCMOE="${NCMOE:-40}"          # offload routed experts for all 40 layers to CPU/RAM
# localhost-only by default. The server is UNAUTHENTICATED — only set HOST=0.0.0.0 if you
# deliberately want it reachable from your LAN (and put it behind a firewall/reverse proxy).
HOST="${HOST:-127.0.0.1}"

echo ">> Serving Ornith-1.0-35B-GGUF:${QUANT}  ctx=${CTX}  port=${PORT}  n-cpu-moe=${NCMOE}"
echo ">> Experts -> system RAM; attention + KV -> GPU. First run downloads ~21.2GB."

exec "${LLAMA_SERVER}" \
  -hf "deepreinforce-ai/Ornith-1.0-35B-GGUF:${QUANT}" \
  --jinja \
  -ngl 99 \
  --n-cpu-moe "${NCMOE}" \
  --ctx-size "${CTX}" \
  --flash-attn \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -b 4096 -ub 4096 \
  --no-mmap \
  --temp 0.6 --top-p 0.95 --top-k 20 \
  --host "${HOST}" --port "${PORT}"

# If "--n-cpu-moe" isn't recognized by your llama.cpp build, replace it with:
#   -ot "exps=CPU"
# To discover exact expert tensor names (if the regex doesn't match qwen3_5_moe):
#   llama-server -hf deepreinforce-ai/Ornith-1.0-35B-GGUF:Q4_K_M -ot ".*=CPU" -v 2>&1 \
#     | grep -E 'exps|ffn' | head

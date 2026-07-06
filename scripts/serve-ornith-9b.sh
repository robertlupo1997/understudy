#!/usr/bin/env bash
# Serve Ornith-1.0-9B (dense) fully on an RTX 3070 (8GB) via llama.cpp.
# Exposes an OpenAI-compatible API at http://localhost:${PORT}/v1
#
# Prereq: llama.cpp built with CUDA (see docs/serving.md). `llama-server` on PATH,
# or set LLAMA_SERVER to its full path.
#
# Usage:  ./serve-ornith-9b.sh            # defaults: Q4_K_M, 16K ctx, port 8000
#         PORT=8001 CTX=8192 ./serve-ornith-9b.sh
set -euo pipefail

LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
QUANT="${QUANT:-Q4_K_M}"      # Q4_K_M (5.63GB) is the only quant that fits 8GB comfortably
CTX="${CTX:-16384}"           # keep <=16384 on 8GB (WSL reserves ~1-1.5GB VRAM)
PORT="${PORT:-8000}"
# localhost-only by default. The server is UNAUTHENTICATED — only set HOST=0.0.0.0 if you
# deliberately want it reachable from your LAN (and put it behind a firewall/reverse proxy).
HOST="${HOST:-127.0.0.1}"

echo ">> Serving Ornith-1.0-9B-GGUF:${QUANT}  ctx=${CTX}  host=${HOST}  port=${PORT}"
echo ">> (dense model — NO expert offload flags)"

exec "${LLAMA_SERVER}" \
  -hf "deepreinforce-ai/Ornith-1.0-9B-GGUF:${QUANT}" \
  --jinja \
  -ngl 99 \
  --ctx-size "${CTX}" \
  --flash-attn \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --temp 0.6 --top-p 0.95 --top-k 20 \
  --host "${HOST}" --port "${PORT}"

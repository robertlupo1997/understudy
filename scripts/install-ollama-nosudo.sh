#!/usr/bin/env bash
# Install Ollama into $HOME with NO sudo (self-contained, bundles its own CUDA runtime).
# This is what was used to get the 9B running on the 3070 in WSL2 on 2026-06-28.
# The official `curl ollama.com/install.sh | sh` needs root; this avoids it.
#
# Result: ~/ollama/bin/ollama  (+ ~/ollama/lib/ with CUDA v13 libs)
set -euo pipefail
DEST="${DEST:-$HOME/ollama}"
mkdir -p "$DEST"

echo ">> ensuring zstd decompressor (python zstandard, user install)..."
python3 -c "import zstandard" 2>/dev/null || \
  pip install --user zstandard 2>/dev/null || \
  pip install --user --break-system-packages zstandard

echo ">> resolving latest linux-amd64 (CUDA) asset..."
URL=$(curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest \
  | grep -oE '"browser_download_url": *"[^"]*ollama-linux-amd64\.tar\.zst"' \
  | sed 's/.*"https/https/; s/"$//' | head -1)
[ -n "$URL" ] || { echo "could not resolve asset URL"; exit 1; }
echo "   $URL"

echo ">> downloading (~1.3GB, resumable)..."
curl -fSL -C - --retry 8 --retry-delay 5 -o "$DEST/ollama.tar.zst" "$URL"

echo ">> extracting (streaming zstd -> tar)..."
python3 - "$DEST" <<'PY'
import zstandard, tarfile, os, sys
dst=sys.argv[1]; src=os.path.join(dst,'ollama.tar.zst')
with open(src,'rb') as f, zstandard.ZstdDecompressor().stream_reader(f) as r, tarfile.open(fileobj=r, mode='r|') as tar:
    tar.extractall(dst, filter='fully_trusted')
print("extracted ->", dst)
PY
rm -f "$DEST/ollama.tar.zst"

echo ">> done. version:"; "$DEST/bin/ollama" --version 2>&1 | head -2
cat <<EOF

Next:
  # start the server (leave running):
  OLLAMA_HOST=127.0.0.1:11434 $DEST/bin/ollama serve &
  # pull + alias the 9B:
  OLLAMA_HOST=127.0.0.1:11434 $DEST/bin/ollama pull hf.co/deepreinforce-ai/Ornith-1.0-9B-GGUF:Q4_K_M
  OLLAMA_HOST=127.0.0.1:11434 $DEST/bin/ollama cp hf.co/deepreinforce-ai/Ornith-1.0-9B-GGUF:Q4_K_M ornith9b
  # smoke test:
  BASE=http://localhost:11434/v1 ./scripts/smoke-test.sh   # (set model to ornith9b)
EOF

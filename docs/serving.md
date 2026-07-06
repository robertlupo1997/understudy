# Serving Ornith-1.0 locally (WSL2 + RTX 3070 + 64GB RAM)

> Goal: a local **OpenAI-compatible** endpoint at `http://localhost:8000/v1` that the
> Claude-orchestrator loop (`architecture.md`) delegates work to. Runnable scripts live in
> `../scripts/`. Everything below is verified against the GitHub README, HF model cards, and
> the 35B `config.json` (2026-06-28).

**Which runtime?** **Ollama for the 9B (start here, verified)** · **llama.cpp for the 35B**
(needs `--n-cpu-moe`) · **vLLM/SGLang only after a 24GB GPU**. Rationale + decision table in
`how-it-works.md` (Part 2).

## Naming gotchas (read first)

- **HF model IDs are dot-zero:** `deepreinforce-ai/Ornith-1.0-9B-GGUF`. The GitHub repo is
  `Ornith-1` (no dot-zero). `Ornith-1-9B` will **404**.
- **Recommended sampling:** `temperature=0.6, top_p=0.95, top_k=20`. (Use `temperature=1.0`
  only to reproduce their benchmark numbers.) No repetition penalty is specified.
- **Always pass `--jinja` to llama.cpp.** Without it, llama.cpp uses a generic template and
  the model's `<tool_call>` XML comes back as **raw text in the content field** — silently
  breaking every agentic tool-use harness. This is the #1 footgun.
- **`<think>...</think>` blocks:** the model is a reasoner; it opens every turn with a
  thinking block. Servers surface this in a `reasoning_content` field (see parsers below).
- **Bind to localhost.** These servers have **no authentication**. Bind to `127.0.0.1` (the
  default in the `scripts/`), not `0.0.0.0`. Only expose on your LAN deliberately — and then
  put it behind a firewall or an auth proxy. With WSL2 mirrored networking, `0.0.0.0` is
  reachable from other machines on your network.

## Path A — llama.cpp (recommended for 8GB; an optional speed-up for the 35B)

### Build once (WSL2, CUDA)

```bash
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(nproc)"
# binaries land in ./build/bin/ (llama-server, llama-cli, ...)
```

> Use the Windows NVIDIA driver — do **not** install a Linux GPU driver inside WSL.
> Verify the GPU is visible: `nvidia-smi` should list your 3070 from inside WSL.

### 9B — fully on the GPU (your daily driver)

```bash
llama-server \
  -hf deepreinforce-ai/Ornith-1.0-9B-GGUF:Q4_K_M \
  --jinja \
  -ngl 99 \
  --ctx-size 16384 \
  --flash-attn \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  --host 127.0.0.1 --port 8000
```

- `-hf ...:Q4_K_M` auto-downloads the 5.63GB quant on first run.
- `-ngl 99` = all layers on GPU. The 9B is **dense** — do **not** add `--n-cpu-moe`/`-ot`.
- Keep `--ctx-size` ≤ 16384 on the 3070: WSL leaves you ~6.5–7GB, and weights (5.63GB) + KV
  must fit. Bump only if `nvidia-smi` shows headroom.

### 35B — expert-offload (experts in RAM, active path on GPU)

```bash
llama-server \
  -hf deepreinforce-ai/Ornith-1.0-35B-GGUF:Q4_K_M \
  --jinja \
  -ngl 99 \
  --n-cpu-moe 40 \
  --ctx-size 32768 \
  --flash-attn \
  --cache-type-k q8_0 --cache-type-v q8_0 \
  -b 4096 -ub 4096 \
  --no-mmap \
  --host 127.0.0.1 --port 8000
```

> ✅ **35B verified on Ollama (2026-06-28), not yet on llama.cpp.** `smoke-test.sh` PASSes against
> `ornith35b` and the full delegation loop works (~14 tok/s gen, 152 tok/s prompt). The HF
> Discussion #9 "fails tool calls / never returns" report is **llama.cpp-specific** — so if you
> serve the 35B via *this* path (llama.cpp), re-run `BASE=http://localhost:8000/v1 MODEL=ornith35b
> scripts/smoke-test.sh` and confirm **PASS** before wiring it in.

What each critical flag does:
- **`--n-cpu-moe 40`** — the magic flag. Routes all 256 routed-expert FFN tensors (across
  all 40 layers) to **system RAM**, while attention, norms, embeddings, the shared expert,
  and the **whole KV cache stay on the GPU**. This is what makes 21.2GB run on 8GB.
  (Equivalent: `-ot "exps=CPU"`.)
- **`--no-mmap`** — force the 21.2GB fully resident in RAM (you have 64GB; do this). Without
  it the model can page from disk and stall. *(If you ever run this on a 32GB box, drop
  `--no-mmap`.)*
- **`--flash-attn`** — required for the quantized KV cache to be fast.
- **`--ctx-size 32768`** — sane default for coding tasks. KV at 32K ≈ 1.34GB (q8_0). You can
  go to 65536 (~2.7GB KV) if VRAM allows. **Never set 262144 (256K) on 8GB** — its KV cache
  alone is ~10.7GB.

If `-ot "exps=CPU"` doesn't match (Qwen3.5 tensor names could differ), discover the real
names: `llama-server --model <file>.gguf -ot ".*=CPU" -v 2>&1 | grep -E 'exps|ffn' | head`.

### KV-cache budget (35B, GQA with 2 KV heads — unusually small)

| Context | FP16 KV | q8_0 KV | Fits 8GB w/ offload? |
|---|---|---|---|
| 8K | 0.67GB | 0.34GB | ✅ trivially |
| 16K | 1.34GB | 0.67GB | ✅ |
| 32K | 2.68GB | 1.34GB | ✅ **(default)** |
| 64K | 5.37GB | 2.68GB | ✅ tight, watch `nvidia-smi` |
| 128K | 10.7GB | 5.37GB | ⚠️ use q4_0 KV |
| 256K | 21.5GB | 10.7GB | ❌ needs ≥24–48GB GPU |

The 2-KV-head GQA makes this cache ~4× smaller than a typical model — which is why a 256K
model can give you a comfortable 32–64K window on an 8GB card.

## Path B — Ollama (easy, 9B only) ✅ VERIFIED on this rig (2026-06-28)

**This is the path we actually ran the 9B on.** No CUDA toolkit, no building — Ollama bundles
its own CUDA runtime. Install with no sudo via `scripts/install-ollama-nosudo.sh`, then:

```bash
OLLAMA_HOST=127.0.0.1:11434 ~/ollama/bin/ollama serve &        # daemon
ollama pull hf.co/deepreinforce-ai/Ornith-1.0-9B-GGUF:Q4_K_M   # ~5.6GB (use the hf.co form)
ollama cp   hf.co/deepreinforce-ai/Ornith-1.0-9B-GGUF:Q4_K_M ornith9b   # short alias
```

Endpoint is `http://localhost:11434/v1` (OpenAI-compatible). Measured results on the RTX 3070:
**56.5 tok/s** generation, 382 tok/s prompt eval, ~6.0 GB VRAM, and **tool-calling returns
proper `tool_calls`** (no `--jinja` needed — Ollama applies the GGUF's embedded template). So
for the 9B, Ollama alone is fully agent-ready.

> The official `ollama` library namespace (`ollama run ornith:9b`) was **not** verified —
> use the `hf.co/deepreinforce-ai/...` form above, which is confirmed working.

⚠️ **Two Ollama caveats:**
1. **Ollama runs the 35B fine — verified ~14 tok/s** on the 3070 + 64GB (gen) / 152 tok/s (prompt).
   It lacks `--n-cpu-moe` (ollama/ollama#11772) so it uses generic offload, but for this **~3B-active
   MoE** that's only mildly slower — *not* the 5–10× the issue implies. llama.cpp `--n-cpu-moe` is an
   **optional** speed-up. Pull: `ollama pull hf.co/deepreinforce-ai/Ornith-1.0-35B-GGUF:Q4_K_M`,
   then `ollama cp … ornith35b`.
2. Ollama's default context is tiny (2–4K) and silently truncates. For agentic use, set
   `PARAMETER num_ctx 32768` in a Modelfile.

## Path C — vLLM / SGLang (only after a 24GB upgrade)

The official high-throughput recipes load **full-precision bf16 weights** — the 9B alone is
~18GB — so they need a **≥24GB card and are not an 8GB option at all** (this is why you use
GGUF + llama.cpp on the 3070):

```bash
# vLLM (>=0.19.1) — drop --tensor-parallel-size for a single GPU:
vllm serve deepreinforce-ai/Ornith-1.0-9B \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 \
  --max-model-len 16384 --gpu-memory-utilization 0.85 --port 8000

# SGLang (>=0.5.9) — note the DIFFERENT parser name:
python -m sglang.launch_server --model-path deepreinforce-ai/Ornith-1.0-9B \
  --tool-call-parser qwen3_coder --reasoning-parser qwen3 \
  --context-length 16384 --port 8000
```

- vLLM parser: **`qwen3_xml`**; SGLang parser: **`qwen3_coder`** (same XML wire format,
  different names). `--reasoning-parser qwen3` splits the `<think>` trace into
  `reasoning_content`.
- These give the best tokens/sec and cleanest tool-call parsing, but they serve the
  unquantized weights, which an 8GB card can't hold. **Recommendation: llama.cpp (GGUF) now;
  switch to vLLM if you get the 3090.**

## Smoke test (do this before wiring up any harness)

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"ornith","messages":[{"role":"user","content":"Reply with exactly: OK"}],
       "temperature":0.6,"top_p":0.95}' | head -c 400
```

Then test **tool calling** (the thing that actually matters for agents): send a request with
a `tools` array and confirm the response contains a structured `tool_calls` field — **not**
raw `<tool_call>` XML inside `content`. If you see raw XML, `--jinja` (llama.cpp) or the
`--tool-call-parser` flag (vLLM/SGLang) is missing or wrong, and every worker harness will
fail silently.

---
_Sources: GitHub README serving recipes; `tokenizer_config.json` + `chat_template.jinja` for
9B/35B; `config.json`; llama.cpp `--n-cpu-moe`/`-ot` docs + discussions; ollama/ollama#11772.
Verified 2026-06-28._

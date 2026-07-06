# How it all works (the explainer)

> Plain-language walkthrough of three things: **the model**, **how we run it on your machine**,
> and **how Claude Code drives it**. Everything here is verified against our own setup
> (2026-06-28).

---

## Part 1 — What Ornith-1.0 is, and how it "works"

**The one-liner:** Ornith-1.0 is an open-weight (MIT) coding model trained not just to *write
code*, but to *plan its own approach* — and you run it for free on your own hardware.

### The clever idea: self-scaffolding (and what it does NOT mean)
Most models are trained to produce an answer. Ornith was trained with reinforcement learning to
produce **two** things each step: a *scaffold* (a plan — how to break the task down, what tools
to call, how to retry) **and** the solution that follows from it. Reward flows back to both, so
over training it learns *good problem-solving strategy*, not just good syntax.

**Important reality check:** this is a **training-time** property. You download **frozen
weights** — the model does **not** learn from your tasks, has no memory across sessions, and
there's no "write a harness, then run it" two-pass mode at inference. What you get is a model
whose *instincts* for planning are baked in. You cash that in by feeding it an **iterative
plan→execute loop** (exactly what our Claude integration does), not by expecting magic from a
one-shot prompt.

### It "thinks" before it answers
Every reply opens with a hidden reasoning block: `<think> … </think>`, then the real answer.
That's why it's good at multi-step work — and why the **`max_tokens` trap** exists: if you give
it too small a token budget, the thinking eats all of it and you get an **empty answer** with a
normal-looking "stop" signal. (We verified this; our worker now defaults to 8192 tokens.)

### Two very different sizes (same family)
| | **9B** (what we run) | **35B** |
|---|---|---|
| Type | **Dense, hybrid** — only 8 of 40 layers use normal attention; the other 32 are "recurrent" (SSM-style) | **Sparse MoE** — 256 experts, but only **8 fire per token** |
| "Active" compute/token | ~9B | **~3B** (that's why it's fast for its size) |
| Why it matters | tiny memory for context (KV cache), fits in 8GB | the 21GB of experts can live in **system RAM**, not VRAM |

Both are **multimodal** (can take images) with a **256K-token** context window — though for
coding we cap context far lower to save memory.

### How good is it, really?
Strong for its size, but **be skeptical of the headline benchmarks** — they're all
vendor-self-reported, and OpenAI formally *abandoned* the main one (SWE-bench Verified) in Feb
2026 for being gameable. The honest read: the **9B is a capable junior dev** that's right most
of the time and wrong ~10% of the time on hard tasks. That ~10% is the entire reason Claude
stays in the loop as reviewer. Details + sources: `usecases.md`.

---

## Part 2 — How we run it on your machine

### GGUF + quantization, in one breath
The model's weights are originally 16-bit numbers (huge). **Quantization** squeezes them to ~4
bits with tiny quality loss — that's the **GGUF** file format. The 9B at "Q4_K_M" is 5.6GB,
which fits in your 3070's 8GB. (Q5/Q6/Q8 = bigger + slightly better; we use Q4.)

### VRAM vs. RAM — the key mental model
- **VRAM** (8GB on your 3070) is fast but small. **System RAM** (64GB) is big but slower.
- The **9B** fits entirely in VRAM → runs fast (~56 tok/s, measured).
- The **35B** (21GB) doesn't fit in VRAM — but because only ~3B params fire per token, you keep
  the rarely-used experts in **RAM** and only the active path on the **GPU**. Verified on your
  rig: **~14 tok/s** (vs the 9B's 56) — slower but usable, running on hardware that "shouldn't"
  handle a 35B. Ollama does this automatically; llama.cpp's `--n-cpu-moe` is an optional speed-up.

### Three ways to serve it — which should you use?
| Runtime | Best for | Tool-calling | Reality for you |
|---|---|---|---|
| **Ollama** ✅ | the **9B, today** | uses the GGUF's built-in template (works for us) | **Start here.** Zero build, bundles CUDA, verified working. |
| **llama.cpp** | the **35B** (needs `--n-cpu-moe`) | needs `--jinja` | Required for the 35B; more control, must build from source. |
| **vLLM / SGLang** | max speed, production | dedicated `qwen3_xml` parser (most robust) | Only worth it **after** a 24GB GPU — needs the full 18GB+ weights. |

**Is Ollama the best way?** *For the 9B right now — yes,* by a wide margin (simplest, proven on
your box). It is **not** a fit for the 35B (no expert-offload) and not the fastest ceiling
(vLLM is). So: **Ollama for the 9B → llama.cpp when you move to the 35B → vLLM if you upgrade.**
Commands for all three: `serving.md`.

---

## Part 3 — How the Claude Code integration works

The goal: **Claude does the thinking; your machine does the typing — for free.** This stretches
your $100 Max plan and keeps Claude's limited context clean.

### The flow (Pattern B — "delegate," not "replace")
```
You ──▶ Claude Code (Opus, your Max plan) = the ORCHESTRATOR
            │   plans, decomposes, writes the acceptance test, REVIEWS
            │
            ▼  spawns the `ornith-worker` subagent (Bash + git worktree)
        worker.py ──HTTP──▶ local Ornith (Ollama, localhost:11434)
            │                          writes the code to a file
            ▼
        returns a 5-line SUMMARY ──▶ Claude reviews + runs the test
```

### Why this preserves context (the part that saves you money)
The worker writes code **to disk** and prints back only a **short summary** — *never the code
itself*. So Claude's context window never fills up with Ornith's verbose output. Claude spends
its (paid) tokens only on planning and reviewing; the (free) local model does the bulk writing.
**Break this rule** — let Claude read the full output — and the savings vanish. That's why it's
written into `CLAUDE.md` and the worker prints summaries by design.

### Who does what
- **Claude (paid, smart):** vague goals → concrete plan, architecture, ambiguity, **reviewing
  correctness/security.**
- **Ornith (free, local):** well-specified functions, tests, mechanical refactors, boilerplate.
- **Rule of thumb:** if a wrong answer is cheap to catch → Ornith. If it's subtle/expensive →
  Claude. The 9B's ~10% miss rate is *why* Claude reviews everything.

### What's actually wired up here
- `orchestration/worker.py` — the local worker (talks to Ornith, writes files, summarizes).
- `agents/local-worker.md` (install to `~/.claude/agents/`) — the subagent Claude dispatches (runs in a throwaway git
  worktree so parallel workers can't collide; **no sandbox on the model itself**, so we isolate it).
- We **proved it end-to-end** twice (`roman.py`, `median()`), and `scripts/integration-test.sh`
  re-checks the whole loop in one command.

### Two patterns — we use the safe one
- **Pattern A** (point Claude Code's whole brain at local Ornith via `ANTHROPIC_BASE_URL`):
  *replaces* Claude with the weaker model and wastes your Max plan. Community couldn't even get
  it working E2E. We don't use it.
- **Pattern B** (above): Claude stays the brain, delegates pieces. **This is ours.**

---

## Part 4 — How to test the integration (anytime)
```bash
./scripts/integration-test.sh     # server → tool-calling → real delegation → verify
```
It checks all four layers and prints `PASS`/`FAIL`. The layer that matters most and is least
reliable: **multi-step tool-calling** — so the standing rule is *Claude always reviews worker
output.* See `docs/gotchas.md` for the verify-list and known gotchas.

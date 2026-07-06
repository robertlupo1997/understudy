# understudy

Claude Code as the brain, a free local model as the hands. `understudy` is the verified
wiring for delegating scoped implementation tasks from Claude Code to a local Ollama
model — with a **propose-only loop** (nothing auto-merges) and a **token-savings contract**
that keeps the local model's verbose output OUT of Claude's context.

Model-agnostic by design; **reference-verified on DeepReinforce's Ornith-1.0 (9B/35B, MIT).**
Other Ollama models are untested — the wiring is generic, the numbers are Ornith's.

## Why
Agentic coding burns paid-model tokens on mechanical typing. A local model types fine;
what it can't do is plan or review. Split the work: Claude plans, decomposes, authors the
check, and reviews; the local worker implements one well-specified file for $0.

## The token-savings contract
- The worker writes code to DISK and prints a short structural summary (files/what/tests/issues).
- The summary contains only structural counts — never model-chosen strings — so it can't
  become a bloat or prompt-injection channel back into the orchestrator.
- The orchestrator spot-checks with targeted reads, never ingests worker transcripts.

## Two ways to use it
- **One-shot worker:** `python3 orchestration/worker.py --task "..." --out path.py`
- **24/7 propose-only loop:** fill `queue/<id>.md` with scoped specs; `python3 -m
  orchestration.loop.run_loop --config config.yaml` drains the queue with zero orchestrator
  tokens — each task builds in a throwaway git worktree, is verified by a bwrap-sandboxed
  gate, and lands as a reviewable diff in `inbox/<id>/` that never auto-merges.

## Quickstart
1. `scripts/install-ollama-nosudo.sh`   # no-root Ollama into ~/ollama
2. `ollama pull <Ornith-1.0-9B GGUF>`   # exact tags in docs/serving.md
3. `bash scripts/smoke-test.sh`         # must print tool-calling PASS
4. `python3 orchestration/worker.py --task "..." --out path.py`
5. Loop: `cp config.example.yaml config.yaml` (point `target_repo` at your repo),
   `cp examples/add-function.md orchestration/loop/queue/`, then run the loop command above.
6. Claude Code users: install `agents/local-worker.md` + `commands/delegate.md`, then `/delegate`.

## Measured (see docs/measurements.md)

RTX 3070 / WSL2 / Ollama — run 2026-07-06.

| | ornith9b | ornith35b |
|-|----------|-----------|
| Throughput (gen tok/s) | 53.1 | 13.6 |
| Head-to-head pass rate | 3/5 (60 %) | 5/5 (100 %) |
| Avg wall-time per task | 8 s | 118 s |

Token-savings: orchestrator receives a 197-byte summary; generated file is 1 778 bytes — **9× more work than context paid for.**

## Safety
The model ships no runtime sandbox. Workers run one-shot in a throwaway git worktree; the
gate runs your repo's trusted steps inside bwrap (no network, $HOME secrets blanked,
read-only worktree, timeout). Nothing auto-merges. `bwrap` is **Linux/WSL only** (macOS: roadmap).

## Read next
- `docs/writing-specs.md` — how to write specs a local model can actually build (the secret sauce).
- `docs/gotchas.md` — the max_tokens/<think> trap, the 35B over-reasoning fix, the chat-template bug.
- `docs/architecture.md` — the propose-only design and the token contract in full.

## Roadmap (not in v0.1)
macOS sandbox · non-Ollama backends · parallel workers · verified multi-model support ·
an agentic worker tier.

MIT © 2026 Robert Lupo

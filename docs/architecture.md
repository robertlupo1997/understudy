# Architecture — Claude Code as orchestrator, Ornith as local worker

> Your goal, in your words: *"turn Claude into an orchestrator who uses these open-source
> models as the implementation agents, to preserve context and have my own computer doing
> the work — and maximize the $100 plan."* This doc is the concrete design for exactly that.

## The two patterns (and why one is right for you)

| | **Pattern A — redirect** | **Pattern B — delegate** ✅ |
|---|---|---|
| What it is | Point Claude Code's own model loop at local Ornith via `ANTHROPIC_BASE_URL` + a shim | Real Claude (Opus) stays the brain; it spawns *separate* local-Ornith CLI workers |
| Who thinks | **Ornith** (Claude is gone) | **Claude** plans/reviews; **Ornith** types the code |
| Claude tokens | ~zero | only planning + spot-checks |
| Your $100 Max plan | **wasted** (sub sits idle) | **stretched** (its tokens go far) |
| Context preserved | n/a | ✅ yes — worker output never enters Claude's window |
| Verdict | niche / offline-only | **this is your architecture** |

Pattern A *replaces* Claude with a weaker model — it doesn't "preserve Claude's context,"
it removes Claude. Useful only when you want a zero-Claude offline session. **Use Pattern B.**

## Pattern B — the design

```
   ┌─────────────────────────────────────────────────────────────┐
   │  Claude Code (Opus)  ── the orchestrator (your $100 Max sub) │
   │  • understands the goal, plans, decomposes into sub-tasks    │
   │  • reviews diffs, resolves ambiguity, makes design calls     │
   │  • spawns workers, reads only their SUMMARIES                 │
   └───────────────┬─────────────────────────────────────────────┘
                   │ Bash subprocess (per task), isolated git worktree
                   ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  ornith-worker  ── a Claude Code subagent (tools: Bash, Read)│
   │  shells out to a local coding CLI:  qwen -p "<task>" --yolo  │
   └───────────────┬─────────────────────────────────────────────┘
                   │ OpenAI-compatible HTTP  →  localhost:8000/v1
                   ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Ornith-1.0 served by llama.cpp  (9B on GPU / 35B offload)   │
   │  writes code to disk in the worktree, returns a short summary│
   └─────────────────────────────────────────────────────────────┘
```

### The pieces

1. **Server** — `scripts/serve-9b.sh` (or `serve-35b.sh`) exposes Ornith at
   `localhost:8000/v1`. See `serving.md`.

2. **Worker harness** — the local CLI agent that drives Ornith. Best fit: **Qwen Code**
   (`QwenLM/qwen-code`) — it's from the same CLI-agent lineage as Claude Code *and* shares
   Ornith's Qwen-3.5 DNA, so its tool-call loop matches Ornith's trained format. Headless:
   ```bash
   qwen -p "<task>" --yolo --max-wall-time 10m
   ```
   Point it at the local endpoint in `~/.config/qwen-code/settings.json`:
   `modelProviders.openai.baseUrl = "http://localhost:8000/v1"`.
   *Alternatives:* `aider --message "<task>" --yes --model openai/ornith
   --openai-api-base http://localhost:8000/v1` (great for single-file edits);
   `opencode run`. **Cline / Roo Code are VSCode-GUI only** — fine for hands-on use, but they
   can't be shelled out from a subagent.

3. **The `ornith-worker` subagent** — `agents/local-worker.md` (install to
   `~/.claude/agents/`). It has `tools: Bash, Read` and `isolation: worktree`, so each worker
   runs on its **own git branch** — parallel workers can't clobber each other. Claude reads
   the diff back, not the worker's chatter.

> ⚠️ A Claude Code subagent's `model:` field only accepts **Claude** aliases
> (opus/sonnet/haiku/fable). You **cannot** set it to Ornith directly — that's *why* the
> worker shells out via Bash instead.

### The token-savings contract (this is the whole point)

Delegation only saves your plan if **Ornith's raw output never enters Claude's context.**
Enforce this everywhere:

- The worker **writes changes to disk** in its worktree and prints a **5–10 line summary**:
  files touched, what changed, any errors. Nothing more.
- Claude's Bash call captures **only that summary** (cap/limit the output — never pipe the
  full worker transcript back).
- Claude **spot-checks** with a targeted `Read` on the specific function that changed — it
  does not ingest the whole diff.

Break this contract (e.g. let Claude read the full worker log) and you're back to burning
Opus tokens on Ornith's verbosity. This rule is written into `CLAUDE.md` and the subagent
prompt so it's enforced by default.

### Division of labor — who does what

| Give to **Ornith (local, free)** | Keep on **Claude (Opus, paid)** |
|---|---|
| Implement a well-specified function | Decompose a vague goal into tasks |
| Write tests for a documented API | Architecture & design decisions |
| Mechanical refactors, boilerplate | Resolve ambiguity / underspecified asks |
| Apply a clearly-described fix | Review correctness & security of diffs |
| Single-file edits with clear scope | Cross-file reasoning over unknown code |

Rule of thumb: **if a wrong answer is cheap to catch, send it to Ornith; if a wrong answer
is expensive or subtle, keep it on Claude.** The 9B has a real ~10% failure rate on harder
tasks (see `usecases.md`) — Claude's job is to be the reviewer that catches it.

## Exploiting the "self-scaffolding" training at inference

Ornith was RL-trained to generate *its own* scaffold (plan/retry/tool-orchestration) and the
solution together. **Important reality check:** that's a **training-time** property —
you get **frozen weights**. It does **not** learn from your tasks, has no memory across
sessions, and there's no "generate-a-harness-then-run-it" two-pass mode at inference. The
scaffold skill is baked into the weights and shows up as its `<think>` reasoning and clean
tool calls.

How you actually benefit: feed it **in-distribution** input — an **iterative plan-then-execute
loop** with prior steps in context, which is exactly what Pattern B does. Claude maintaining
a running plan and handing Ornith one scoped, context-rich step at a time is the practical
way to cash in what the scaffold-RL taught it. Don't expect magic from one-shot prompts.

## Safety — Ornith ships NO runtime guardrails

The "trust boundary / deterministic monitor / frozen-judge" safety layers you may read about
are **training-only** anti-reward-hacking mechanisms. **None ship in the weights.** A local
Ornith worker running with `--yolo` will do whatever it decides — including `rm`, network
calls, or editing files outside scope. You are the sandbox. Minimum precautions:

- Run workers in the **git worktree** isolation (already in the subagent) — limits blast
  radius to a throwaway branch.
- Keep them inside **WSL**, not touching `/mnt/c` system paths; consider a dedicated project
  dir or a Docker container for anything untrusted.
- Don't hand workers broad shell permissions or secrets. Treat worker output as untrusted
  until Claude reviews it.

## Pattern A, if you ever want it (zero-Claude offline sessions)

Point Claude Code at local Ornith with a translation shim (Claude speaks the Anthropic
Messages API; Ornith speaks OpenAI):

```bash
# LiteLLM proxy translates Anthropic <-> OpenAI:
export ANTHROPIC_BASE_URL=http://localhost:4000
export ANTHROPIC_AUTH_TOKEN=<litellm_master_key>
```

🚨 **Two warnings:**
1. **Supply-chain:** LiteLLM **1.82.7 / 1.82.8 shipped credential-stealing malware** (PyPI
   account hijack). **Pin to a verified clean release** (post-1.82.8, from the GitHub release
   notes) and rotate creds if you ever installed those versions.
2. **ToS / value:** routing your *own* session to your *own* local model isn't a documented
   violation, but the moment you set `ANTHROPIC_AUTH_TOKEN` to a gateway key your **Max sub
   goes idle** — you're not stretching the plan, you're replacing Claude. Also: the Claude
   Code **Agent SDK requires an API key** (not Max OAuth) for headless/automated runs — keep
   the orchestrator **interactive** to stay on your subscription.

---
_Sources: Claude Code docs (llm-gateway, sub-agents, agent-teams); Qwen Code / aider /
opencode headless docs; LiteLLM docs + BerriAI/litellm#24518 (malware advisory);
community `rafw007/ornith-1.0-9b-claude-coder` (a working Claude-Code+Ornith setup).
Verified 2026-06-28._

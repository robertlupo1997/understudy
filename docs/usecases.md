# Use cases & honest expectations

> What Ornith-1.0 is actually for, what the 9B vs 35B can each do, and how much to trust the
> headline numbers. Written for a solo dev trying to ship and make money — so the framing is
> "what earns its keep," not "what benchmarks well."

## What it's built for

DeepReinforce targets **agentic software engineering** — multi-step, tool-using coding
loops, not one-shot autocomplete. The benchmarks tell you the intended jobs:

- **Terminal-Bench** → running terminal/agent tasks end to end.
- **SWE-bench Verified/Pro/Multilingual** → repository-level bug repair (find + fix + pass tests).
- **NL2Repo** → natural-language → navigate/modify a repo.
- **ClawEval** → real-user task distributions.

The self-scaffolding training makes it specifically good inside an **iterative plan→execute
loop** — which is precisely the Claude-orchestrator pattern you want (`architecture.md`).

## Early reception (it's ~1 week old — calibrate accordingly)

- **Real traction:** 35B-GGUF ~80K downloads / 396 likes, 9B-GGUF ~37K / 264, in one week.
  GGUF downloads >> base-model downloads → people are running it **locally**, which is your
  use case.
- r/LocalLLaMA and X are "making noise," but most hands-on reports are on **big hardware**
  (DGX Spark, RTX 5090, Mac). Take size-specific praise with that grain of salt.
- **Someone already built your exact setup:** `rafw007/ornith-1.0-9b-claude-coder` on HF — a
  9B tuned as a **Claude Code worker** via Ollama's API. Reported ~17 tok/s on a Mac Mini M4,
  and the model recovered from a blocked `sudo` by switching to Python sockets (real agentic
  persistence). This validates the architecture — read that card before you wire yours.

## Trust the benchmarks? Partially. Here's the discount.

- **All Ornith scores are self-reported.** ornith.site says so outright: *"independent
  verification is pending as of June 2026."*
- **SWE-bench Verified is structurally inflated for every model** — ~30% of instances leak the
  fix in the issue text, and ~20% of "resolved" patches fail strengthened tests. Treat
  **Verified** as optimistic.
- **OpenAI formally abandoned SWE-bench Verified (Feb 2026)** over contamination + scaffolding
  inflation; the public leaderboard is ~99/100 self-reported with no standardized harness. So
  every Ornith score is an unreproduced vendor self-report.
- **SWE-bench Pro is the number to trust** (private codebases, harder to game). The gap is
  telling:

  | | SWE-V (optimistic) | **SWE-Pro (trust this)** |
  |---|---|---|
  | Ornith 9B | 69.4 | **42.9** |
  | Ornith 35B | 75.6 | **50.4** |
  | (ref) Claude Opus 4.5 | 80.9 | 45.9 |

  Read that bottom row carefully: on the *honest* benchmark, the **35B (50.4) is in the same
  league as a frontier model (45.9)** for repo-level repair. That's genuinely strong for
  something running on your desk — but it's *one* benchmark; verify on *your* code.

## What each tier should actually do

### Ornith-9B (your GPU daily driver) — reliable for:
- single-function / single-file implementation
- writing unit tests for documented APIs
- fixing bugs with clear error messages
- explaining code in context, small fast patches
- being the **executor** in a Claude-orchestrated loop

…with a **~10% failure rate on harder tasks** even at good quant (independent 40-task test).
So: great for volume, *needs Claude's review on anything subtle.*

### Ornith-35B (when quality matters and you can wait):
- the same jobs, but **~2% failure** instead of ~10% — meaningfully more reliable
- multi-file changes with more context
- worth the slower offload speed for *hard* tasks; use the 9B for the rest

### Keep on Claude (Opus) regardless:
- turning vague goals into concrete plans
- architecture / design trade-offs
- ambiguity resolution, correctness & security review
- anything where a subtle wrong answer is expensive

## Known rough edges (from the one independent hands-on test)

- Persistent small-logic slips: **operator precedence**, **banker's rounding** edge cases.
- The 9B "looks right but is wrong" ~10% of the time on hard problems — which is exactly the
  failure mode your Claude reviewer exists to catch.
- Benchmarks are **Python-heavy**; performance on your actual stack (TS/Go/Rust/etc.) may
  differ. **Run your own 10–20 task spot-check** in your real language before trusting it.

## How this makes you money (the actual point)

- **Cost structure:** Claude does the thinking (paid, where quality pays off); Ornith does
  the typing (free, local, unlimited). Your $100 Max plan stretches because Opus tokens stop
  being spent on boilerplate and file edits.
- **Privacy:** local execution means client/private repos never leave your machine — a real
  selling point if you take on contract work.
- **Throughput:** with worktree isolation you can fan out several Ornith workers in parallel
  on independent sub-tasks while Claude reviews — more shipped per hour.

## First experiment to run

1. Serve the 9B (`scripts/serve-9b.sh`), smoke-test tool calling (`serving.md`).
2. Take a **real** small task from your own work. Have Claude plan it and delegate the
   implementation to `ornith-worker`. Review the diff.
3. Note: did the 9B's output need heavy fixing? How many Claude tokens did you spend vs doing
   it all in Claude? That single data point tells you whether to (a) lean in, (b) try the
   35B, or (c) buy the 3090.

---
_Sources: GitHub README + HF cards (use cases, engagement); ornith.site (self-reported
disclaimer); codeant.ai + independent SWE-bench analyses (contamination); note.com/zephel01
(40-task local test); `rafw007/ornith-1.0-9b-claude-coder`. Verified 2026-06-28.
Self-reported and analog figures flagged as such throughout._

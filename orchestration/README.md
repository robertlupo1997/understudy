# orchestration/ — wiring Claude → Ornith

This dir holds the glue for **Pattern B** (see `../docs/architecture.md`): Claude Code stays
the orchestrator; `ornith-worker` delegates scoped implementation to the local Ornith server.

## Files
- **`ornith-worker.md`** — a Claude Code subagent that shells out to a local coding CLI
  (Qwen Code / aider) pointed at Ornith, runs in an isolated git worktree, and returns only
  a short summary.

## One-time setup

1. **Serve Ornith** (pick one, see `../docs/serving.md`):
   ```bash
   ../scripts/serve-ornith-9b.sh      # daily driver, fully on the 3070
   # or: ../scripts/serve-ornith-35b.sh   # higher quality, expert-offload to RAM
   ```
   Verify: `../scripts/smoke-test.sh` → must say tool calling PASS ✅.

2. **Install a worker harness** (Qwen Code recommended — shares Ornith's Qwen lineage):
   ```bash
   npm install -g @qwen-code/qwen-code        # provides the `qwen` CLI
   ```
   Configure its endpoint in `~/.config/qwen-code/settings.json`:
   ```json
   { "modelProviders": { "openai": {
       "baseUrl": "http://localhost:8000/v1", "apiKey": "dummy",
       "models": ["ornith"] } } }
   ```
   (Alternative harness: `pipx install aider-chat`.)

3. **Install the subagent** so Claude Code can call it:
   ```bash
   mkdir -p ~/.claude/agents
   cp ornith-worker.md ~/.claude/agents/        # (or symlink to keep it versioned here)
   ```

## Using it

In a Claude Code session, just ask Claude to delegate, e.g.:

> "Plan the change. For each implementation step, use the **ornith-worker** subagent to write
>  the code, then review its summary and spot-check the diff."

Claude plans → spawns `ornith-worker` per task → each worker edits files on its own worktree
branch via local Ornith → Claude reads back only the summaries and reviews. Your Opus tokens
go to thinking and reviewing; the typing is free and local.

## The rule that makes it worth it

Workers return **summaries, not transcripts.** If Claude ever ingests a worker's full output,
the context/token savings evaporate. This contract is baked into `ornith-worker.md` and
`../CLAUDE.md`. See `../docs/architecture.md#the-token-savings-contract`.

## Safety

Local Ornith has **no runtime sandbox** (`../docs/architecture.md#safety`). Workers run with
`--yolo` inside a throwaway worktree — keep them there, don't grant broad permissions or
secrets, and let Claude review before anything merges.

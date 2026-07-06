---
description: Delegate scoped implementation work to the local coding model (free) via the local-worker subagent — preserves Claude usage
argument-hint: <task description, file paths, acceptance criteria>
---

Delegate the following work to the LOCAL coding model (free, runs on this machine) instead of implementing it on Claude. You are the brain; the local worker is the hands.

**Task:** $ARGUMENTS

## Procedure

1. **Preflight the server.** `curl -s --max-time 3 http://localhost:11434/v1/models | head -c 300`. If it is down, do NOT start it yourself — tell the user to start their local model server and stop until it's up.

2. **Scope check.** The local worker takes ONE well-specified task: a named function, tests for a documented API, a mechanical refactor of a named module, a clearly-described fix, boilerplate. If the request is vague, cross-file, security-sensitive, or a subtle wrong answer would be expensive: decompose it into worker-sized pieces first, or keep it on Claude and say why. Local models have a real failure rate on hard tasks — you are the reviewer that catches it.

3. **Delegate.** Spawn the `local-worker` agent (Agent tool, `subagent_type: "local-worker"`) with a fully-specified brief: exact file paths, signatures/interfaces, acceptance criteria, and the test command to run. One scoped task per worker; fire independent tasks in parallel.

4. **Token-savings contract — do not violate.** The worker returns a 5–10 line summary (files changed / what / tests / issues). NEVER read a worker's full transcript or full diff into your context. Spot-check with a targeted Read of only the changed function. Breaking this collapses the whole point of delegation.

5. **Review and report.** Run the brief's test command yourself, spot-check the diff, then report: what was delegated, worker summary, test results, anything you fixed or rejected.

Reference: `orchestration/worker.py` is the bundled zero-dep worker. Use `max_tokens >= 8192` — too-low budgets cause the model's reasoning block to eat the budget and return empty output.

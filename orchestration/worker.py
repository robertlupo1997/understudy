#!/usr/bin/env python3
"""
worker.py — a minimal LOCAL implementation worker (reference model: Ornith-1.0).

This is the "hands" in the Claude-orchestrator / Ornith-worker loop (see docs/architecture.md).
Claude (the orchestrator) hands this script ONE scoped task + a target file. It asks the local
Ornith model to write the whole file, extracts the code, writes it to disk, and prints ONLY a
short summary to stdout. The model's verbose reasoning/output never goes back to Claude — that
is the token-savings contract that preserves Claude's context.

Zero dependencies (stdlib urllib). Talks to the OpenAI-compatible endpoint Ollama/llama.cpp expose.

Usage:
  python3 worker.py --task "<what to build>" --out demo/roman.py
  python3 worker.py --task "..." --out path.py --base http://localhost:11434/v1 --model ornith9b
"""
import argparse, json, os, re, sys, tempfile, time, urllib.request, urllib.error

INSTRUCTION = (
    "You are a precise coding worker. Implement EXACTLY what is requested. "
    "Output the COMPLETE contents of the single target file inside ONE fenced code block "
    "(```python ... ```). Put NOTHING after the closing fence. Do not include explanations "
    "outside the code block. Include any needed imports. Write clean, correct, idiomatic code."
)

class WorkerError(Exception):
    """A controlled worker failure that maps to the structured stderr + exit-2 contract."""


def parse_response(data):
    """Extract (content, finish_reason) from an OpenAI-compatible chat response.

    Raises WorkerError (not KeyError/IndexError) on a malformed or empty response, so a
    misbehaving server can't crash the worker with the wrong exit code in 24/7 mode.
    """
    choices = data.get("choices") if isinstance(data, dict) else None
    if not choices:
        raise WorkerError("response contained no choices")
    ch = choices[0]
    if not isinstance(ch, dict):
        raise WorkerError("response choice is not an object")
    msg = ch.get("message") or {}
    return (msg.get("content") or ""), ch.get("finish_reason")


def summarize(code, out, model, secs, retried):
    """Bounded summary for stdout. NEVER includes model-chosen strings (identifier names,
    file content) — only structural counts — so the token-savings contract can't be used as a
    bloat or prompt-injection channel back into the orchestrator.
    """
    n_lines = code.count("\n")
    n_defs = len(re.findall(r"^(?:async def|def|class)\s+\w+", code, re.MULTILINE))
    note = "none (auto-retried with thinking disabled after a spiral)" if retried else "none"
    return "\n".join([
        f"files changed: {out}",
        f"what was done: wrote {n_lines} lines / {len(code)} bytes; {n_defs} top-level defs",
        "tests/build:   not run by worker (orchestrator verifies)",
        f"issues:        {note} ({secs:.1f}s, model={model})",
    ])


def resolve_out_path(out, allowed_dir):
    """Canonicalize --out. If allowed_dir is set, the resolved path MUST be inside it
    (defense-in-depth against a compromised queue/orchestrator directing writes to e.g.
    ~/.ssh/authorized_keys). allowed_dir=None preserves legacy unconfined behavior."""
    resolved = os.path.realpath(out)
    if allowed_dir is not None:
        base = os.path.realpath(allowed_dir)
        if resolved != base and not resolved.startswith(base + os.sep):
            raise WorkerError(f"--out resolves outside --allowed-dir ({base}): {resolved}")
    return resolved


def write_output(path, code):
    """Atomic write: temp file in the destination dir + os.replace, so a process killed
    mid-write can never leave a half-written (corrupt) output file."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(code)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def call(base, model, task, temperature, max_tokens, timeout, no_think=False):
    url = base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": INSTRUCTION},
            {"role": "user", "content": task},
        ],
        "temperature": temperature,
        "top_p": 0.95,
        "max_tokens": max_tokens,
    }
    if no_think:
        # Ollama /v1 disables the <think> block via reasoning_effort=none. Fixes the 35B
        # over-reasoning spiral (think eats the whole budget, no code emitted). Verified
        # 2026-06-29. NB: chat_template_kwargs={"enable_thinking":false} is silently ignored.
        payload["reasoning_effort"] = "none"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        d = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WorkerError(f"non-JSON response from {url}: {e}")
    return parse_response(d)

_OPEN_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*$")
_CLOSE_FENCE = re.compile(r"```[ \t]*$")


def extract_code(text):
    """Return the LAST COMPLETE fenced code block (+trailing newline), or None.

    Line-anchored scanner (fences must start at column 0), robust to two silent-wrong-output
    traps the adversarial review found:
      (a) a ``` inside an INDENTED docstring/example — an indented fence never starts at
          column 0, so it can't close the block early;
      (b) a TRUNCATED final block — if the stream ends while still inside a block, return
          None (fail loudly) instead of writing an earlier, stale block.
    """
    blocks, cur = [], None
    for line in text.split("\n"):
        if cur is None:
            if _OPEN_FENCE.match(line):
                cur = []
        elif _CLOSE_FENCE.match(line):
            blocks.append("\n".join(cur))
            cur = None
        else:
            cur.append(line)
    if cur is not None:
        return None  # ended inside an unterminated block → truncated
    if blocks:
        return blocks[-1].strip("\n") + "\n"
    return None

def should_retry(code, finish, no_think):
    """Retry once with thinking OFF when the thinking-ON attempt produced no code.

    Broadened from the old `finish == 'length'` check: the documented trap is EMPTY
    content with a BENIGN finish_reason too, and a no-think retry at the same budget is
    cheap. Only fires when thinking was on, so the retry itself cannot recurse.
    """
    return (not code) and (not no_think)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base", default="http://localhost:11434/v1")
    ap.add_argument("--model", default="ornith9b")
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--allowed-dir", default=None,
                    help="if set, --out MUST resolve inside this dir (harness confinement)")
    ap.add_argument("--no-think", action="store_true",
                    help="disable the model's <think> reasoning (reasoning_effort=none); faster, "
                         "and avoids the 35B over-reasoning spiral on hard tasks")
    a = ap.parse_args()

    t0 = time.time()
    retried = False
    try:
        out_path = resolve_out_path(a.out, a.allowed_dir)
        content, finish = call(a.base, a.model, a.task, a.temperature, a.max_tokens, a.timeout, a.no_think)
        code = extract_code(content)
        if should_retry(code, finish, a.no_think):
            retried = True
            content, finish = call(a.base, a.model, a.task, a.temperature, a.max_tokens,
                                   a.timeout, no_think=True)
            code = extract_code(content)
    except (urllib.error.URLError, WorkerError) as e:
        print(f"issues: WORKER_FAILED - {e}", file=sys.stderr)
        sys.exit(2)

    if not code:
        hint = (" - hit the token limit even with thinking disabled; the task likely needs "
                "decomposition" if finish == "length" else "")
        retry_note = " (retry-with-no-think also failed)" if retried else ""
        print(f"issues: WORKER_FAILED - model returned no fenced code block{hint}{retry_note}",
              file=sys.stderr)
        sys.exit(3)

    write_output(out_path, code)
    print(summarize(code, out_path, a.model, time.time() - t0, retried))

if __name__ == "__main__":
    main()

# Writing specs the local worker can actually build

The loop is only as good as the specs you feed it. A 9B model can implement a
well-scoped file and fails an ambiguous one. These are the rules that moved our
dogfood pass rate from "coin-flip" to "mergeable-after-review."

## A spec is a task file in the queue
Each `queue/<id>.md` is one scoped task. It carries everything the worker needs —
the worker sees only this file, never your conversation.

## The five rules
1. **One file, one deliverable.** Name the exact file and the exact function/behavior.
   "Add `int_to_roman(n)` to `roman.py`" — not "improve the roman numeral support."
2. **Carry the context.** The worker has no repo memory. Paste the signatures, the
   data shapes, the error types to raise. If it needs a constant, give the constant.
3. **Author the check yourself.** Every spec includes a `check_cmd` YOU wrote — the
   objective pass/fail. A worker-authored check never earns an auto-pass badge; it
   routes to needs_human. The check is the contract.
4. **Decompose the hard ones.** If a task spans multiple files or needs a design
   decision, it's yours, not the worker's. Split it into single-file specs first.
5. **Reject → sharpen → requeue.** When a diff is wrong, the fix is almost always a
   sharper spec, not a smarter model. Add the missing constraint and requeue. Our
   real dogfood loop merged 5 model-written tests this way.

## Anti-patterns that produce garbage
- Vague verbs: "handle", "support", "improve", "clean up".
- Hidden cross-file coupling the spec doesn't mention.
- A `check_cmd` that passes trivially (e.g. imports but asserts nothing).
- Asking for architecture ("design the API") — that's the orchestrator's job.

## The division of labor
You (the orchestrator model) plan, decompose, author checks, and review. The local
worker types. Keep that line and the loop pays for itself; blur it and you get a
fast way to generate wrong code.

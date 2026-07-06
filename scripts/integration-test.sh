#!/usr/bin/env bash
# End-to-end integration test of the Claude -> Ornith delegation loop.
# Proves all four layers in one command:
#   1. server reachable   2. chat + tool-calling parse   3. worker delegates a real task
#   4. the delegated code passes an objective acceptance test
#
# Usage:  ./scripts/integration-test.sh
#         BASE=http://localhost:8000/v1 MODEL=ornith9b ./scripts/integration-test.sh
set -uo pipefail
BASE="${BASE:-http://localhost:11434/v1}"
MODEL="${MODEL:-ornith9b}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rc=0

echo "### Integration test — $BASE ($MODEL)"

echo; echo "[1/4] server reachable…"
if curl -fsS "${BASE%/v1}/v1/models" >/dev/null 2>&1 || curl -fsS "${BASE%/v1}/api/version" >/dev/null 2>&1; then
  echo "  ✅ up"
else
  echo "  ❌ server not reachable at $BASE — start it (scripts/serve-ornith-9b.sh or ollama serve)"; exit 1
fi

echo; echo "[2/4] chat + tool-calling…"
BASE="$BASE" MODEL="$MODEL" "$HERE/scripts/smoke-test.sh" | sed 's/^/  /' || rc=1

echo; echo "[3/4] delegate a real task to the local worker…"
python3 "$HERE/orchestration/worker.py" --base "$BASE" --model "$MODEL" \
  --out "$TMP/stats.py" \
  --task "Write a function median(nums) that returns the median of a non-empty list of numbers (average of the two middle values for even length). Pure function, no prints." \
  | sed 's/^/  /' || rc=1

echo; echo "[4/4] verify the delegated code (orchestrator review)…"
if python3 - "$TMP" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
try:
    from stats import median
    assert median([5]) == 5
    assert median([1,2,3]) == 2
    assert median([1,2,3,4]) == 2.5
    assert median([7,1,3,2]) == 2.5
    print("  ✅ median() correct on all cases")
except Exception as e:
    print(f"  ❌ FAILED: {e}"); sys.exit(1)
PY
then :; else rc=1; fi

echo; if [ "$rc" -eq 0 ]; then echo "### RESULT: PASS ✅  the Claude->Ornith loop works end-to-end"; else echo "### RESULT: FAIL ❌  (see above)"; fi
exit "$rc"
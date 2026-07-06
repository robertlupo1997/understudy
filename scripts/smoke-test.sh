#!/usr/bin/env bash
# Verify a local Ornith endpoint is alive AND that tool-calling parses correctly.
# A passing chat test but failing tool test means the chat template / parser is wrong —
# every agent harness then fails silently. See docs/serving.md.
#
# Defaults target our verified Ollama setup. For llama.cpp: BASE=http://localhost:8000/v1
# Usage:  ./smoke-test.sh
#         BASE=http://localhost:8000/v1 MODEL=ornith9b ./smoke-test.sh
set -uo pipefail
BASE="${BASE:-http://localhost:11434/v1}"
MODEL="${MODEL:-ornith9b}"
# max_tokens kept high on purpose: Ornith emits a <think> block first; too small a budget
# yields EMPTY content with a benign finish_reason (verified gotcha). See community-findings.md.

echo "== endpoint: $BASE  model: $MODEL =="

echo "== 1. plain chat =="
curl -fsS "${BASE}/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\":\"$MODEL\",
  \"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly the two letters: OK\"}],
  \"temperature\":0.6,\"top_p\":0.95,\"max_tokens\":2048
}" | python3 -c "import sys,json; m=json.load(sys.stdin)['choices'][0]['message']; c=(m.get('content') or '').strip(); print('  content ->', repr(c[-60:]) if c else 'EMPTY (FAIL: <think> ate the budget?)')"
echo

echo "== 2. tool calling (the one that matters) =="
RESP=$(curl -fsS "${BASE}/chat/completions" -H 'Content-Type: application/json' -d "{
  \"model\":\"$MODEL\",
  \"messages\":[{\"role\":\"user\",\"content\":\"List the files in the current directory. You MUST use the run_shell tool.\"}],
  \"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"run_shell\",\"description\":\"Run a shell command\",\"parameters\":{\"type\":\"object\",\"properties\":{\"cmd\":{\"type\":\"string\"}},\"required\":[\"cmd\"]}}}],
  \"tool_choice\":\"auto\",\"temperature\":0.6,\"max_tokens\":2048
}")
echo "$RESP" | python3 -c "
import sys,json
m=json.load(sys.stdin)['choices'][0]['message']; tc=m.get('tool_calls'); c=m.get('content') or ''
if tc: print('  PASS ✅  tool:', tc[0]['function']['name'], '| args:', tc[0]['function'].get('arguments'))
elif '<tool_call>' in c or '<function' in c: print('  FAIL ❌  raw XML in content (template/parser wrong). head:', repr(c[:120]))
else: print('  ?? no tool call emitted. content head:', repr(c[:120]))
"
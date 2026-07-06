#!/usr/bin/env python3
"""9B vs 35B head-to-head on objectively-testable coding tasks.

Delegates each task to each model via orchestration/ornith_worker.py, runs a strict
acceptance test on the generated code, and reports pass/fail + wall-time per (model, task).
This is OUR data — the published 9B-vs-35B benchmark deltas were refuted as unverified
(see docs/community-findings.md), so a local head-to-head is the trustworthy comparison.

Usage:  python3 scripts/head-to-head.py                 # ornith9b vs ornith35b
        python3 scripts/head-to-head.py ornith9b        # one model
        BASE=http://localhost:11434/v1 python3 scripts/head-to-head.py
"""
import subprocess, sys, os, time, importlib.util, tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(HERE, "orchestration", "ornith_worker.py")
BASE = os.environ.get("BASE", "http://localhost:11434/v1")

# SECURITY NOTE: this file contains NO eval() call. The string "eval()" appears only inside a
# task prompt that instructs the model NOT to use it; the function under test is named
# evaluate() and the tests call it directly. Nothing here executes attacker-controlled input
# beyond importing model-generated solution files in a throwaway temp dir (your own local model).

# --- acceptance tests (the orchestrator's job: objective, strict) ---
def test_lru(m):
    L = m.LRUCache(2); L.put(1, 1); L.put(2, 2)
    assert L.get(1) == 1
    L.put(3, 3)                      # should evict key 2 (LRU)
    assert L.get(2) in (None, -1), "key 2 should have been evicted"
    assert L.get(3) == 3
    L.put(4, 4)                      # should evict key 1 (now LRU)
    assert L.get(1) in (None, -1) and L.get(4) == 4
    return True

def test_merge(m):
    assert m.merge_intervals([[1, 3], [2, 6], [8, 10], [15, 18]]) == [[1, 6], [8, 10], [15, 18]]
    assert m.merge_intervals([[1, 4], [4, 5]]) == [[1, 5]]
    assert m.merge_intervals([[1, 4], [0, 4]]) == [[0, 4]]
    return True

def test_balanced(m):
    for s, exp in [("()[]{}", True), ("([{}])", True), ("(]", False),
                   ("([)]", False), ("", True), ("(((", False)]:
        assert m.is_balanced(s) == exp, f"is_balanced({s!r}) != {exp}"
    return True

def test_version(m):
    assert m.compare_versions("1.2.0", "1.10.0") == -1, "1.2 < 1.10 numerically"
    assert m.compare_versions("1.0.0", "1.0.0") == 0
    assert m.compare_versions("2.0", "1.9.9") == 1
    assert m.compare_versions("2.0", "2.0.0") == 0
    return True

def test_calc(m):
    for expr, exp in [("2+3*4", 14), ("10-2-3", 5), ("2*3+4*5", 26), ("100/10/2", 5)]:
        assert m.evaluate(expr) == exp, f"evaluate({expr!r}) != {exp}"
    return True

TASKS = [
    ("lru_cache", "O(1) get/put with LRU eviction (dict + doubly linked list)",
     "Write a class LRUCache with __init__(self, capacity), get(self, key) returning the value "
     "or -1 if absent, and put(self, key, value). Evict the least-recently-used item when over "
     "capacity. get and put must be O(1) (dict + doubly linked list). No prints.", test_lru),
    ("merge_intervals", "merge overlapping/touching intervals",
     "Write a function merge_intervals(intervals) taking a list of [start,end] integer pairs and "
     "returning a new list of non-overlapping intervals sorted by start, merging any that overlap "
     "or touch. E.g. [[1,3],[2,6],[8,10]] -> [[1,6],[8,10]]. Pure function.", test_merge),
    ("balanced", "balanced/nested brackets ()[]{}",
     "Write a function is_balanced(s) returning True iff the brackets in s are balanced and "
     "correctly nested, for (), [], and {}. Ignore non-bracket chars. Empty string is balanced. "
     "Pure function.", test_balanced),
    ("version", "NUMERIC dotted-version compare (classic string-compare trap)",
     "Write compare_versions(a, b) comparing two dotted version strings NUMERICALLY (not "
     "lexically). Return -1 if a<b, 0 if equal, 1 if a>b. Missing trailing components count as 0 "
     "('2.0' == '2.0.0'). compare_versions('1.2.0','1.10.0') == -1. Pure function.", test_version),
    ("calc", "operator precedence without eval() (known model weak spot)",
     "Write evaluate(expr) that evaluates an arithmetic string of non-negative integers and the "
     "binary operators + - * / with correct precedence (* and / before + and -), left-to-right "
     "for equal precedence, no parentheses. '100/10/2' -> 5. Do NOT use eval(). Pure function.",
     test_calc),
]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, "could not build module spec"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def run(models):
    res = {}
    for model in models:
        print(f"\n--- {model} ---")
        for name, _desc, prompt, test in TASKS:
            out = os.path.join(tempfile.mkdtemp(), "sol.py")
            t0 = time.time()
            try:
                p = subprocess.run([sys.executable, WORKER, "--base", BASE, "--model", model,
                                    "--out", out, "--task", prompt, "--max-tokens", "8192"],
                                   capture_output=True, text=True, timeout=400)
                secs = time.time() - t0
                if not os.path.exists(out):
                    res[(model, name)] = ("NO_CODE", secs, (p.stderr or p.stdout).strip()[:100])
                else:
                    test(load(out, f"{model}_{name}"))
                    res[(model, name)] = ("PASS", secs, "")
            except AssertionError as e:
                res[(model, name)] = ("WRONG", time.time() - t0, str(e)[:110])
            except Exception as e:
                res[(model, name)] = ("ERROR", time.time() - t0, f"{type(e).__name__}: {str(e)[:90]}")
            st, secs, detail = res[(model, name)]
            mark = "OK " if st == "PASS" else "XX "
            print(f"  {mark}{name:16} {st:7} {secs:5.1f}s  {detail}")
    return res

if __name__ == "__main__":
    models = sys.argv[1:] or ["ornith9b", "ornith35b"]
    print(f"# 9B vs 35B head-to-head — {len(TASKS)} tasks x {len(models)} models @ {BASE}")
    res = run(models)
    print("\n=== SUMMARY ===")
    for model in models:
        rows = [res[(model, t[0])] for t in TASKS]
        npass = sum(1 for r in rows if r[0] == "PASS")
        tot = sum(r[1] for r in rows)
        print(f"  {model:10}  {npass}/{len(TASKS)} pass   total {tot:.0f}s   avg {tot/len(TASKS):.0f}s/task")
    print("\nPer-task winner (correctness; speed as tiebreak):")
    for name, desc, *_ in TASKS:
        line = "  " + f"{name:16} "
        for model in models:
            st, secs, _ = res[(model, name)]
            line += f"{model}={st}({secs:.0f}s)  "
        print(line + f"  [{desc}]")

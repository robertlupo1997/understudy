import os
import ornith_worker as w
import pytest


def test_extract_code_single_block():
    assert w.extract_code("```python\nx = 1\n```\n") == "x = 1\n"


def test_extract_code_returns_last_block():
    # a <think> counter-example block, then the real answer
    text = "```python\nwrong = 0\n```\nthinking...\n```python\nright = 1\n```\n"
    assert w.extract_code(text) == "right = 1\n"


def test_extract_code_ignores_indented_nested_fence():
    # a triple-backtick inside an indented docstring must NOT close the block early
    text = (
        "```python\n"
        "def f():\n"
        '    """\n'
        "    ```\n"
        "    example\n"
        "    ```\n"
        '    """\n'
        "    return 1\n"
        "```\n"
    )
    code = w.extract_code(text)
    assert code.startswith("def f():")
    assert code.rstrip().endswith("return 1")


def test_extract_code_truncated_final_block_returns_none():
    # one complete block, then a truncated (unterminated) final block → must NOT return the stale block
    text = "```python\nstale = 0\n```\n```python\ndef real():\n    return"
    assert w.extract_code(text) is None


def test_extract_code_no_fence_returns_none():
    assert w.extract_code("just prose, no code") is None


def test_should_retry_on_empty_when_finish_length():
    assert w.should_retry(None, "length", no_think=False) is True


def test_should_retry_on_empty_when_finish_benign():
    # the documented trap: EMPTY content with a BENIGN finish_reason must ALSO retry
    assert w.should_retry(None, "stop", no_think=False) is True


def test_should_not_retry_when_code_present():
    assert w.should_retry("x = 1\n", "stop", no_think=False) is False


def test_should_not_retry_when_already_no_think():
    assert w.should_retry(None, "length", no_think=True) is False


def test_parse_response_normal():
    data = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
    assert w.parse_response(data) == ("hi", "stop")


def test_parse_response_empty_choices_raises():
    with pytest.raises(w.WorkerError):
        w.parse_response({"choices": []})


def test_parse_response_missing_choices_raises():
    with pytest.raises(w.WorkerError):
        w.parse_response({})


def test_parse_response_missing_message_is_empty_content():
    data = {"choices": [{"finish_reason": "stop"}]}
    assert w.parse_response(data) == ("", "stop")


def test_summarize_excludes_model_chosen_identifiers():
    code = "def secret_exfil_routine():\n    return 1\n"
    out = w.summarize(code, "/tmp/wt/sol.py", "ornith9b", 1.2, retried=False)
    assert "secret_exfil_routine" not in out      # no model-chosen strings in the summary
    assert "1 top-level defs" in out               # structural count instead
    assert "files changed: /tmp/wt/sol.py" in out


def test_summarize_notes_retry():
    out = w.summarize("x = 1\n", "/tmp/o.py", "ornith35b", 3.0, retried=True)
    assert "auto-retried" in out


def test_resolve_out_path_no_confinement_returns_abspath():
    assert w.resolve_out_path("sub/x.py", None) == os.path.realpath("sub/x.py")


def test_resolve_out_path_inside_allowed_ok(tmp_path):
    allowed = str(tmp_path)
    target = os.path.join(allowed, "pkg", "x.py")
    assert w.resolve_out_path(target, allowed) == os.path.realpath(target)


def test_resolve_out_path_traversal_rejected(tmp_path):
    allowed = str(tmp_path)
    with pytest.raises(w.WorkerError):
        w.resolve_out_path(os.path.join(allowed, "..", "evil.py"), allowed)


def test_resolve_out_path_absolute_escape_rejected(tmp_path):
    with pytest.raises(w.WorkerError):
        w.resolve_out_path("/etc/passwd", str(tmp_path))


def test_write_output_atomic_writes_content(tmp_path):
    p = os.path.join(str(tmp_path), "out.py")
    w.write_output(p, "x = 1\n")
    with open(p) as f:
        assert f.read() == "x = 1\n"
    # no leftover temp files
    assert [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")] == []


def _run_main(monkeypatch, argv, fake_call):
    """Run main() with argv and a stubbed call(); return (exit_code, stdout, stderr)."""
    import io
    monkeypatch.setattr(w, "call", fake_call)
    monkeypatch.setattr(w.sys, "argv", ["ornith_worker.py", *argv])
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(w.sys, "stdout", out)
    monkeypatch.setattr(w.sys, "stderr", err)
    code = 0
    try:
        w.main()
    except SystemExit as e:
        code = e.code or 0
    return code, out.getvalue(), err.getvalue()


def test_main_success_writes_file_and_bounded_summary(monkeypatch, tmp_path):
    target = os.path.join(str(tmp_path), "sol.py")
    fake = lambda *a, **k: ("```python\ndef add(a, b):\n    return a + b\n```\n", "stop")
    code, out, err = _run_main(monkeypatch, ["--task", "add", "--out", target], fake)
    assert code == 0
    with open(target) as f:
        assert "def add(a, b):" in f.read()
    assert "files changed:" in out
    assert "add" not in out  # no model-chosen identifier leaks into the summary


def test_main_no_code_exits_3(monkeypatch, tmp_path):
    target = os.path.join(str(tmp_path), "sol.py")
    fake = lambda *a, **k: ("I cannot help with that.", "stop")
    code, out, err = _run_main(monkeypatch, ["--task", "x", "--out", target], fake)
    assert code == 3
    assert "WORKER_FAILED" in err


def test_main_out_outside_allowed_dir_exits_2(monkeypatch, tmp_path):
    fake = lambda *a, **k: ("```python\nx = 1\n```\n", "stop")
    code, out, err = _run_main(
        monkeypatch,
        ["--task", "x", "--out", "/etc/passwd", "--allowed-dir", str(tmp_path)],
        fake,
    )
    assert code == 2
    assert "WORKER_FAILED" in err


def test_parse_response_non_dict_choice_raises_workererror():
    import ornith_worker as w
    with pytest.raises(w.WorkerError):
        w.parse_response({"choices": [None]})


def test_call_non_json_raises_workererror(monkeypatch):
    import io, ornith_worker as w

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"<html>not json</html>"

    monkeypatch.setattr(w.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    with pytest.raises(w.WorkerError):
        w.call("http://x/v1", "m", "task", 0.3, 128, 5)


def test_resolve_out_path_empty_allowed_dir_still_confines(tmp_path):
    import ornith_worker as w
    # empty-string allowed_dir must NOT silently disable confinement
    with pytest.raises(w.WorkerError):
        w.resolve_out_path("/etc/passwd", "")

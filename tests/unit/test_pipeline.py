"""Pipeline orchestration: ordering, fail-fast exit codes, error redaction and the run log."""

import json

from cloudspend import pipeline


def _stage(name, rc, calls):
    def fn():
        calls.append(name)
        return rc
    return name, fn


def test_runs_all_stages_in_order_and_logs(tmp_path):
    calls = []
    code, res = pipeline.run([_stage("a", 0, calls), _stage("b", 0, calls)], tmp_path / "runs.jsonl")
    assert code == 0 and calls == ["a", "b"] and [r.name for r in res] == ["a", "b"]
    entry = json.loads((tmp_path / "runs.jsonl").read_text().splitlines()[-1])
    assert entry["status"] == "success" and [s["name"] for s in entry["stages"]] == ["a", "b"]


def test_fails_fast_and_returns_the_failing_code(tmp_path):
    calls = []
    code, res = pipeline.run([_stage("a", 0, calls), _stage("b", 2, calls), _stage("c", 0, calls)], tmp_path / "r.jsonl")
    assert code == 2 and calls == ["a", "b"] and res[-1].exit_code == 2
    assert json.loads((tmp_path / "r.jsonl").read_text())["status"] == "failed"


def test_exception_is_reported_without_its_message(tmp_path, capsys):
    def boom():
        raise RuntimeError("password=hunter2")
    code, _ = pipeline.run([("x", boom)], tmp_path / "r.jsonl")
    out = capsys.readouterr().out
    assert code == 1 and "RuntimeError" in out and "hunter2" not in out


def test_local_mode_has_no_snowflake_stages(tmp_path):
    names = [n for n, _ in pipeline.build_stages("local", "demo", 42, tmp_path, regenerate=True, setup=False)]
    assert names == ["generate", "validate", "models"]
    names = [n for n, _ in pipeline.build_stages("snowflake", "demo", 42, tmp_path, regenerate=False, setup=True)]
    assert names == ["generate", "validate", "load_raw", "transform_and_reconcile", "models"]


def test_existing_data_skips_generation(tmp_path):
    (tmp_path / "cloud_billing_demo.csv").write_text("x")
    (tmp_path / "budgets_demo.csv").write_text("x")
    names = [n for n, _ in pipeline.build_stages("local", "demo", 42, tmp_path, regenerate=False, setup=False)]
    assert names == ["validate", "models"]


def test_end_to_end_local_run_on_small_profile(tmp_path):
    from cloudspend.data_generation.generate_billing import PROFILES
    profile = min(PROFILES, key=lambda k: k != "dev")   # prefer the small dev profile
    stages = pipeline.build_stages("local", profile, 42, tmp_path, regenerate=True, setup=False)[:2]   # generate + validate
    code, res = pipeline.run(stages, tmp_path / "r.jsonl")
    assert code == 0 and [r.name for r in res] == ["generate", "validate"]

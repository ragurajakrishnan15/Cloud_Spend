"""First-run bootstrap: builds only what is missing, and does nothing when everything exists."""

from cloudspend import bootstrap


def test_nothing_missing_means_no_work(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "GENERATED_DIR", tmp_path)
    monkeypatch.setattr(bootstrap.model_store, "OUTPUT_DIR", tmp_path / "model_outputs")
    (tmp_path / "model_outputs").mkdir()
    for f in ("cloud_billing_demo.csv", "budgets_demo.csv", *bootstrap.model_store.FILES.values()):
        ((tmp_path / "model_outputs") if f in bootstrap.model_store.FILES.values() else tmp_path).joinpath(f).write_text("x")
    assert bootstrap._missing() == []
    assert bootstrap.ensure_demo_data() == []


def test_missing_pieces_are_reported_in_order(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "GENERATED_DIR", tmp_path)
    monkeypatch.setattr(bootstrap.model_store, "OUTPUT_DIR", tmp_path / "model_outputs")
    assert bootstrap._missing() == ["data", "models"]

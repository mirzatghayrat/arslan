"""Local fastembed provider: absent-safe, download state machine."""
import anyio


def test_provider_none_when_model_absent(tmp_path, monkeypatch):
    from server.services import local_embedding as le
    monkeypatch.setattr(le, "_cache_dir", lambda: tmp_path / "models")
    assert le.provider_if_ready() is None
    assert le.download_status()["status"] == "absent"


def test_download_status_error_when_fastembed_missing(tmp_path, monkeypatch):
    """fastembed 未安装时 download 报 error 状态而非炸。"""
    import builtins
    from server.services import local_embedding as le
    monkeypatch.setattr(le, "_cache_dir", lambda: tmp_path / "models")
    real_import = builtins.__import__
    def block(name, *a, **kw):
        if name.startswith("fastembed"):
            raise ImportError("No module named 'fastembed'")
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", block)
    anyio.run(le.download_local_model)
    st = le.download_status()
    assert st["status"] == "error" and "fastembed" in (st["error"] or "")


def test_provider_ready_when_onnx_present(tmp_path, monkeypatch):
    from server.services import local_embedding as le
    d = tmp_path / "models" / "m"
    d.mkdir(parents=True)
    (d / "model.onnx").write_bytes(b"x")
    monkeypatch.setattr(le, "_cache_dir", lambda: tmp_path / "models")
    p = le.provider_if_ready()
    assert p is not None and p.model_id == le.LOCAL_MODEL_ID
    assert le.download_status()["status"] == "ready"

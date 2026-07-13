"""Local fastembed provider: absent-safe, download state machine."""


def test_provider_none_when_model_absent(tmp_path, monkeypatch):
    from server.services import local_embedding as le
    monkeypatch.setattr(le, "_cache_dir", lambda: tmp_path / "models")
    assert le.provider_if_ready() is None
    assert le.download_status()["status"] == "absent"


async def test_download_status_error_when_fastembed_missing(tmp_path, monkeypatch):
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
    await le.download_local_model()
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


async def test_embed_preserves_order_and_coerces_float(monkeypatch):
    """LocalEmbeddingProvider.embed() must return vectors in the same order
    as the input texts (providers/models must not silently reorder), and
    every component must be a plain float (not numpy scalar/int) since the
    result is packed with struct.pack('<{n}f', ...) downstream."""
    import numpy as np
    from server.services import local_embedding as le

    class FakeModel:
        def embed(self, texts):
            # distinct, known vectors — one per input, numpy arrays like the
            # real fastembed model would yield.
            for i, _ in enumerate(texts):
                yield np.array([float(i), float(i) + 0.5], dtype=np.float32)

    monkeypatch.setattr(le, "_model", FakeModel())
    provider = le.LocalEmbeddingProvider()
    texts = ["第一", "第二", "第三"]
    vecs = await provider.embed(texts)

    assert len(vecs) == len(texts)
    for i, vec in enumerate(vecs):
        assert vec == [float(i), float(i) + 0.5]
        for x in vec:
            assert isinstance(x, float)

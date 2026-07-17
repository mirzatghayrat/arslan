import os
import stat

from server.mcp_server import token_store


def test_generate_is_random_persisted_0600_and_matches(tmp_path):
    t1 = token_store.generate_mcp_token(data_dir=tmp_path)
    t2 = token_store.generate_mcp_token(data_dir=tmp_path)  # rotate
    assert t1 and t2 and t1 != t2                 # random, and rotate changes it
    assert len(t1) >= 32
    path = tmp_path / "mcp_token"
    assert path.read_text().strip() == t2         # latest persisted
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert token_store.read_mcp_token(data_dir=tmp_path) == t2
    assert token_store.mcp_token_matches(t2, data_dir=tmp_path) is True
    assert token_store.mcp_token_matches(t1, data_dir=tmp_path) is False  # old rejected → rotate is real


def test_matches_is_false_for_empty_or_absent(tmp_path):
    assert token_store.mcp_token_matches(None, data_dir=tmp_path) is False
    assert token_store.mcp_token_matches("anything", data_dir=tmp_path) is False  # no token file yet
    token_store.generate_mcp_token(data_dir=tmp_path)
    assert token_store.mcp_token_matches("", data_dir=tmp_path) is False


def test_clear_removes_file_and_closes(tmp_path):
    token_store.generate_mcp_token(data_dir=tmp_path)
    token_store.clear_mcp_token(data_dir=tmp_path)
    assert token_store.read_mcp_token(data_dir=tmp_path) == ""
    token_store.clear_mcp_token(data_dir=tmp_path)  # idempotent, no raise


def test_not_derived_from_secret_key(tmp_path, monkeypatch):
    # The MCP token must be independent of ARSLAN_SECRET_KEY: changing the secret
    # does not change the stored MCP token.
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "secret-A" * 4)
    t = token_store.generate_mcp_token(data_dir=tmp_path)
    monkeypatch.setenv("ARSLAN_SECRET_KEY", "secret-B" * 4)
    assert token_store.read_mcp_token(data_dir=tmp_path) == t


def test_uses_compare_digest_not_plain_equality(tmp_path, monkeypatch):
    # Spec Q3 detail 1 / test 4(d): the compare MUST be constant-time compare_digest,
    # not ==. Spy on the symbol and assert it is actually invoked.
    import server.mcp_server.token_store as ts
    real = ts.secrets.compare_digest
    calls = []

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(ts.secrets, "compare_digest", spy)
    tok = token_store.generate_mcp_token(data_dir=tmp_path)
    assert token_store.mcp_token_matches(tok, data_dir=tmp_path) is True
    assert calls, "mcp_token_matches must use secrets.compare_digest (constant-time), not =="


def test_not_equal_to_app_api_token(tmp_path, monkeypatch):
    # Spec test item 5: the dedicated MCP token is independent of the app api_token.
    monkeypatch.setenv("ARSLAN_API_TOKEN", "app-token-value-0123456789")
    tok = token_store.generate_mcp_token(data_dir=tmp_path)
    assert tok != "app-token-value-0123456789"


def test_non_ascii_bearer_is_false_not_raise(tmp_path):
    # A non-ASCII bearer must fail closed (False → 401), never raise (→ 500).
    token_store.generate_mcp_token(data_dir=tmp_path)
    assert token_store.mcp_token_matches("\xff\xfe", data_dir=tmp_path) is False

"""Tests for _0006_provider_configs migration."""
import sqlalchemy as sa
from server import crypto
from server.db.migrations.versions import _0006_provider_configs as m6


def _conn():
    eng = sa.create_engine("sqlite://")
    return eng.connect()


def test_creates_table_and_is_idempotent():
    conn = _conn()
    m6.upgrade_sync(conn)
    m6.upgrade_sync(conn)  # second run must not raise
    names = set(sa.inspect(conn).get_table_names())
    assert "provider_configs" in names


def test_backfills_existing_single_key_as_primary():
    conn = _conn()
    conn.execute(sa.text("CREATE TABLE settings (key VARCHAR(100) PRIMARY KEY, value TEXT NOT NULL)"))
    conn.execute(sa.text("INSERT INTO settings (key, value) VALUES "
                         "('llm_provider','deepseek'),('llm_model','deepseek-chat'),"
                         "('llm_base_url',''),('llm_api_key', :k)"),
                 {"k": crypto.encrypt("sk-secret-123456")})
    m6.upgrade_sync(conn)
    rows = list(conn.execute(sa.text("SELECT provider, model, api_key, is_primary FROM provider_configs")))
    assert len(rows) == 1
    assert rows[0][0] == "deepseek"
    assert rows[0][3] in (1, True)
    assert crypto.decrypt(rows[0][2]) == "sk-secret-123456"  # NOT re-encrypted
    strat = conn.execute(sa.text("SELECT value FROM settings WHERE key='llm_strategy'")).scalar_one()
    assert strat == "single"

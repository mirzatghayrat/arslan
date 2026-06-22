from server.db.models import ProviderConfig


def test_provider_config_columns():
    cols = {c.name for c in ProviderConfig.__table__.columns}
    assert cols == {"id", "label", "provider", "model", "base_url", "api_key", "is_primary", "created_at"}
    assert ProviderConfig.__tablename__ == "provider_configs"

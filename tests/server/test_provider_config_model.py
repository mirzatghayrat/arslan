from server.db.models import ProviderConfig


def test_provider_config_columns():
    cols = {c.name for c in ProviderConfig.__table__.columns}
    # last_health / last_health_at added by migration 0031 (Provider round P2,
    # consumed by the P4 health probe).
    assert cols == {"id", "label", "provider", "model", "base_url", "api_key",
                    "is_primary", "created_at", "last_health", "last_health_at",
                    "last_health_detail"}
    assert ProviderConfig.__tablename__ == "provider_configs"

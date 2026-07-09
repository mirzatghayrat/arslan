"""P0-2 secret/auth hardening: env-gated settings + boot validation."""
from __future__ import annotations

import importlib
import logging

import pytest


def _reload_config(monkeypatch, **env):
    for key in ("ARSLAN_ENV", "ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_BIND_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    import server.config as config

    return importlib.reload(config)


# --- config field tests -----------------------------------------------------


def test_env_defaults_to_dev(monkeypatch):
    config = _reload_config(monkeypatch)
    assert config.settings.env == "dev"
    assert config.settings.is_prod is False


def test_is_prod_true_when_env_prod(monkeypatch):
    config = _reload_config(monkeypatch, ARSLAN_ENV="prod")
    assert config.settings.env == "prod"
    assert config.settings.is_prod is True


def test_env_is_lowercased(monkeypatch):
    config = _reload_config(monkeypatch, ARSLAN_ENV="PROD")
    assert config.settings.env == "prod"
    assert config.settings.is_prod is True


def test_bind_host_defaults_to_localhost(monkeypatch):
    config = _reload_config(monkeypatch)
    assert config.settings.bind_host == "127.0.0.1"


def test_bind_host_from_env(monkeypatch):
    config = _reload_config(monkeypatch, ARSLAN_BIND_HOST="0.0.0.0")
    assert config.settings.bind_host == "0.0.0.0"


# --- validation tests -------------------------------------------------------


def _validate(monkeypatch, **env):
    config = _reload_config(monkeypatch, **env)
    import server.main as main

    return main, config.settings


def test_prod_missing_secret_refuses_boot(monkeypatch):
    main, cfg = _validate(monkeypatch, ARSLAN_ENV="prod")
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    msg = str(exc.value)
    assert "ARSLAN_SECRET_KEY" in msg
    assert "refusing to start" in msg


def test_prod_refuse_message_does_not_echo_secrets(monkeypatch):
    """小条件1: the boot-refusal message must not leak any configured secret."""
    main, cfg = _validate(
        monkeypatch, ARSLAN_ENV="prod", ARSLAN_API_TOKEN="supersecret"
    )
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    assert "supersecret" not in str(exc.value)


def test_dev_missing_secret_does_not_raise_and_warns(monkeypatch, caplog):
    main, cfg = _validate(monkeypatch)  # dev, no secret
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)  # must not raise
    assert any("ARSLAN_SECRET_KEY not set" in r.message for r in caplog.records)


def test_prod_with_secret_does_not_raise(monkeypatch):
    # prod also needs a token now (item c), so supply both to isolate the secret check.
    main, cfg = _validate(
        monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok"
    )
    main._validate_settings(cfg)  # must not raise


def test_missing_api_token_logs_banner(monkeypatch, caplog):
    main, cfg = _validate(monkeypatch, ARSLAN_SECRET_KEY="x" * 32)
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert any("ARSLAN_API_TOKEN not set" in r.message for r in caplog.records)
    assert any("UNAUTHENTICATED" in r.message for r in caplog.records)


def test_api_token_set_no_banner(monkeypatch, caplog):
    main, cfg = _validate(
        monkeypatch, ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok"
    )
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert not any("ARSLAN_API_TOKEN not set" in r.message for r in caplog.records)


def test_prod_missing_token_refuses_boot(monkeypatch):
    """item c: prod + empty ARSLAN_API_TOKEN -> refuse to boot, like SECRET_KEY."""
    main, cfg = _validate(monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    msg = str(exc.value)
    assert "ARSLAN_API_TOKEN" in msg
    assert "refusing to start" in msg


def test_prod_token_refuse_message_does_not_echo_secrets(monkeypatch):
    """The token-refusal message must not leak the configured secret_key value."""
    main, cfg = _validate(
        monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="leakysecretvalue123456789012"
    )
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    assert "leakysecretvalue123456789012" not in str(exc.value)


def test_prod_with_token_does_not_raise(monkeypatch):
    main, cfg = _validate(
        monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok"
    )
    main._validate_settings(cfg)  # must not raise


def test_bind_0000_no_token_warns(monkeypatch, caplog):
    main, cfg = _validate(
        monkeypatch, ARSLAN_SECRET_KEY="x" * 32, ARSLAN_BIND_HOST="0.0.0.0"
    )
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert any("exposed to the network" in r.message for r in caplog.records)


def test_localhost_bind_no_exposure_warning(monkeypatch, caplog):
    main, cfg = _validate(monkeypatch, ARSLAN_SECRET_KEY="x" * 32)
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert not any("exposed to the network" in r.message for r in caplog.records)


# --- test-route prod gate (P0-3) --------------------------------------------
# The `/api/v1/_test/seed_spawn` helper creates a spawn with NO auth. It is
# env-gated behind ARSLAN_TEST_ROUTES=1, but if that flag ever leaks into a
# prod deployment the endpoint would let anyone forge spawns. Defense in depth:
# refuse to register it whenever ARSLAN_ENV=prod, regardless of the flag.

_SEED_ROUTE = "/api/v1/_test/seed_spawn"


def _app_paths(monkeypatch, **env):
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    config = _reload_config(monkeypatch, **env)
    # _reload_config clears ARSLAN_ENV et al but leaves ARSLAN_TEST_ROUTES.
    import server.main as main

    app = main.create_app()
    return {getattr(r, "path", None) for r in app.routes}, config.settings


def test_seed_spawn_route_registered_in_dev(monkeypatch):
    paths, cfg = _app_paths(monkeypatch)  # dev + ARSLAN_TEST_ROUTES=1
    assert cfg.is_prod is False
    assert _SEED_ROUTE in paths


def test_seed_spawn_route_absent_in_prod(monkeypatch):
    paths, cfg = _app_paths(
        monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32
    )
    assert cfg.is_prod is True
    assert _SEED_ROUTE not in paths


def test_seed_spawn_route_absent_without_flag(monkeypatch):
    monkeypatch.delenv("ARSLAN_TEST_ROUTES", raising=False)
    _reload_config(monkeypatch)  # dev, no flag
    import server.main as main

    paths = {getattr(r, "path", None) for r in main.create_app().routes}
    assert _SEED_ROUTE not in paths

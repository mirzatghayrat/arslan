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
    main, cfg = _validate(monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
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


def test_prod_no_token_adds_stern_line(monkeypatch, caplog):
    main, cfg = _validate(monkeypatch, ARSLAN_ENV="prod", ARSLAN_SECRET_KEY="x" * 32)
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert any(
        "ARSLAN_ENV=prod with no ARSLAN_API_TOKEN" in r.message for r in caplog.records
    )


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

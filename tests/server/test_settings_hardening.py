"""P0-2 secret/auth hardening: env-gated settings + boot validation."""
from __future__ import annotations

import importlib
import logging

import pytest


def _reload_config(monkeypatch, **env):
    for key in ("ARSLAN_ENV", "ARSLAN_PACKAGED", "ARSLAN_SECRET_KEY", "ARSLAN_API_TOKEN", "ARSLAN_BIND_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    import server.config as config

    return importlib.reload(config)


# --- config field tests -----------------------------------------------------


def test_not_packaged_by_default(monkeypatch):
    # C11 (v0.1.63): the desktop app's server (ARSLAN_PACKAGED) replaced ARSLAN_ENV=prod.
    config = _reload_config(monkeypatch)
    assert config.settings.packaged is False
    assert not hasattr(config.settings, "is_prod")


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_packaged_when_the_flag_is_truthy(monkeypatch, value):
    assert _reload_config(monkeypatch, ARSLAN_PACKAGED=value).settings.packaged is True


@pytest.mark.parametrize("value", ["0", "false", ""])
def test_not_packaged_when_the_flag_is_falsy(monkeypatch, value):
    assert _reload_config(monkeypatch, ARSLAN_PACKAGED=value).settings.packaged is False


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


def test_packaged_missing_secret_refuses_boot(monkeypatch):
    main, cfg = _validate(monkeypatch, ARSLAN_PACKAGED="1")
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    msg = str(exc.value)
    assert "ARSLAN_SECRET_KEY" in msg
    assert "refusing to start" in msg


def test_packaged_refuse_message_does_not_echo_secrets(monkeypatch):
    """小条件1: the boot-refusal message must not leak any configured secret."""
    main, cfg = _validate(
        monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_API_TOKEN="supersecret"
    )
    with pytest.raises(RuntimeError) as exc:
        main._validate_settings(cfg)
    assert "supersecret" not in str(exc.value)


def test_dev_missing_secret_does_not_raise_and_warns(monkeypatch, caplog):
    # The suite-wide ARSLAN_SECRET_KEY_FILE="" (tests/conftest.py) disables secret
    # auto-generation, so a reload with no ARSLAN_SECRET_KEY still yields an empty
    # secret here — pinning the pre-existing warn-and-continue dev behaviour.
    main, cfg = _validate(monkeypatch)  # dev, no secret, auto-gen disabled
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)  # must not raise
    assert any("ARSLAN_SECRET_KEY not set" in r.message for r in caplog.records)


def test_dev_missing_secret_autogenerates_when_enabled(monkeypatch, caplog, tmp_path):
    """Keyless dev boot + feature enabled -> a real secret, no insecure-dev warning."""
    main, cfg = _validate(monkeypatch, ARSLAN_SECRET_KEY_FILE=str(tmp_path / "sk"))
    assert cfg.secret_key
    assert (tmp_path / "sk").read_text(encoding="utf-8") == cfg.secret_key
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert not any("ARSLAN_SECRET_KEY not set" in r.message for r in caplog.records)


def test_packaged_whitespace_secret_refuses_boot(monkeypatch):
    """Whitespace-only is UNSET to crypto (strip) — the packaged boot check must agree."""
    main, cfg = _validate(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="   ")
    with pytest.raises(RuntimeError):
        main._validate_settings(cfg)


def test_dev_whitespace_secret_warns(monkeypatch, caplog):
    """Dev half of the strip alignment: whitespace-only must trigger the same
    insecure-dev warning as unset (crypto derives from the PUBLIC fallback)."""
    main, cfg = _validate(monkeypatch, ARSLAN_SECRET_KEY="   ")
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg)
    assert any("ARSLAN_SECRET_KEY not set" in r.message for r in caplog.records)


def test_packaged_reads_the_persisted_secret_file_and_starts(monkeypatch, tmp_path):
    """packaged + keyless + a populated secret file -> uses it (C11: prod skipped it)."""
    f = tmp_path / "sk"
    f.write_text("persisted-secret", encoding="utf-8")
    main, cfg = _validate(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY_FILE=str(f))
    assert cfg.secret_key == "persisted-secret"
    main._validate_settings(cfg, active_token="tok")  # must not raise


def test_undecryptable_canary_mentions_secret_file_mismatch():
    """The canary must point at the env-vs-persisted-file mismatch as a likely cause,
    stay %-formattable (a stray literal % would make the logging handler swallow the
    whole line), and actually be the string the lifespan canary emits."""
    from pathlib import Path

    import server.main as main

    assert "auto-generated" in main._UNDECRYPTABLE_KEYS_MSG
    assert "ARSLAN_SECRET_KEY_FILE" in main._UNDECRYPTABLE_KEYS_MSG
    assert "3 stored provider" in (main._UNDECRYPTABLE_KEYS_MSG % 3)
    # Source-level pin against re-inlining a literal at the call site, which would
    # orphan this constant while the test kept passing.
    assert "logger.warning(_UNDECRYPTABLE_KEYS_MSG" in Path(main.__file__).read_text(
        encoding="utf-8"
    )


def test_packaged_with_secret_does_not_raise(monkeypatch):
    main, cfg = _validate(
        monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok"
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


# S1-3 SUPERSEDES item c: packaged + empty ARSLAN_API_TOKEN does not HARD-refuse to
# boot. The token bootstrap (server.token_bootstrap, covered by
# test_token_bootstrap.py) auto-generates + enforces a token before serving, so a
# packaged build never crashes and never runs fully open. _validate_settings
# therefore must NOT raise on a missing token (secret_key refusal is unchanged).
def test_packaged_missing_token_does_not_refuse_boot(monkeypatch):
    """packaged + no token -> _validate_settings does not raise (bootstrap handles it)."""
    main, cfg = _validate(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32)
    # Must not raise. Enforcement is now provided by token_bootstrap, not by refusing.
    main._validate_settings(cfg)


def test_packaged_with_active_token_no_unauth_banner(monkeypatch, caplog):
    """When the bootstrap supplies an active token, the UNAUTHENTICATED banner is silent."""
    main, cfg = _validate(monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32)
    with caplog.at_level(logging.WARNING):
        main._validate_settings(cfg, active_token="boot-minted-token")
    assert not any("UNAUTHENTICATED" in r.message for r in caplog.records)


def test_packaged_with_token_does_not_raise(monkeypatch):
    main, cfg = _validate(
        monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32, ARSLAN_API_TOKEN="tok"
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


# --- test-route packaged gate (P0-3, C11) -------------------------------------
# The `/api/v1/_test/seed_spawn` helper creates a spawn with NO auth. It is
# env-gated behind ARSLAN_TEST_ROUTES=1, but if that flag ever leaks into a
# packaged app the endpoint would let anyone forge spawns. Defense in depth:
# refuse to register it in the desktop app's server, regardless of the flag.

_SEED_ROUTE = "/api/v1/_test/seed_spawn"


def _app_paths(monkeypatch, **env):
    monkeypatch.setenv("ARSLAN_TEST_ROUTES", "1")
    config = _reload_config(monkeypatch, **env)
    # _reload_config clears ARSLAN_ENV et al but leaves ARSLAN_TEST_ROUTES.
    import server.main as main

    app = main.create_app()
    from tests.route_introspection import iter_route_paths
    return iter_route_paths(app), config.settings


def test_seed_spawn_route_registered_in_dev(monkeypatch):
    paths, cfg = _app_paths(monkeypatch)  # dev + ARSLAN_TEST_ROUTES=1
    assert cfg.packaged is False
    assert _SEED_ROUTE in paths


def test_seed_spawn_route_absent_when_packaged(monkeypatch):
    paths, cfg = _app_paths(
        monkeypatch, ARSLAN_PACKAGED="1", ARSLAN_SECRET_KEY="x" * 32
    )
    assert cfg.packaged is True
    assert _SEED_ROUTE not in paths


def test_seed_spawn_route_absent_without_flag(monkeypatch):
    monkeypatch.delenv("ARSLAN_TEST_ROUTES", raising=False)
    _reload_config(monkeypatch)  # dev, no flag
    import server.main as main

    paths = {getattr(r, "path", None) for r in main.create_app().routes}
    assert _SEED_ROUTE not in paths

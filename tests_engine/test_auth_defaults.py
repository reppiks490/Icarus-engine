from __future__ import annotations

import pytest


def test_engine_cli_requires_environment_token_before_runtime(monkeypatch):
    from icarus_engine import cli

    monkeypatch.delenv("ICARUS_TOKEN", raising=False)
    monkeypatch.delenv("ICARUS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_portfolio", lambda *_args, **_kwargs: pytest.fail("runtime must not start"))
    with pytest.raises(SystemExit) as error:
        cli.main(["run"])
    assert error.value.code == 2


def test_engine_server_requires_explicit_or_environment_token(monkeypatch):
    from icarus_engine.server import serve

    monkeypatch.delenv("ICARUS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ICARUS_TOKEN"):
        serve(None, 0, start=False)


def test_legacy_environment_token_is_supported_and_placeholders_are_ignored(monkeypatch):
    from icarus_engine.server import configured_owner_token, resolve_owner_token

    monkeypatch.setenv("ICARUS_TOKEN", "icarus")
    monkeypatch.setenv("ICARUS_ADMIN_TOKEN", "legacy-explicit-test-secret")
    assert configured_owner_token() == "legacy-explicit-test-secret"
    monkeypatch.setenv("ICARUS_ADMIN_TOKEN", "replace-me-too")
    monkeypatch.setenv("ADMIN_TOKEN", "change-me-too")
    assert configured_owner_token() == ""
    with pytest.raises(ValueError, match="non-placeholder"):
        resolve_owner_token("icarus")


def test_cli_does_not_print_configured_token(monkeypatch, capsys):
    from icarus_engine import cli, server

    class Journal:
        path = "test-journal"
        def log(self, *_args): pass

    class Portfolio:
        order = ["NQ"]
        def start(self): pass
        def stop(self): pass

    monkeypatch.delenv("ICARUS_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("ICARUS_TOKEN", "private-auth-test-token")
    monkeypatch.setattr(cli, "Journal", lambda *_args, **_kwargs: Journal())
    monkeypatch.setattr(cli, "_portfolio", lambda *_args, **_kwargs: Portfolio())
    monkeypatch.setattr(server, "serve", lambda *_args, **_kwargs: None)
    assert cli.main(["run", "--assets", "NQ"]) == 0
    output = capsys.readouterr().out
    assert "private-auth-test-token" not in output
    assert "authentication token configured" in output.lower()


def test_active_auth_paths_have_no_fixed_token_or_cli_forwarding():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths = ("icarus_engine/cli.py", "icarus_engine/server.py", "icarus_engine/dashboard.html",
             "start-engine-background.ps1")
    for relative in paths:
        source = (root / relative).read_text(encoding="utf-8")
        assert "default=\"icarus\"" not in source, relative
        assert "token: str = \"icarus\"" not in source, relative
        assert "terminal default" not in source.lower(), relative
        assert "--token" not in source, relative
    dashboard = (root / "icarus_engine/dashboard.html").read_text(encoding="utf-8")
    assert "localStorage.setItem(tokKey, 'icarus')" not in dashboard
    assert "fetch('/api/research'" in dashboard

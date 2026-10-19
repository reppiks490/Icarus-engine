"""Guest sharing is opt-in and never reuses the live ICARUS admin credential."""
from types import SimpleNamespace

from icarus_engine import cli, guest_server


def test_cli_guest_activation_is_off_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(guest_server, "activate", lambda *a, **k: calls.append((a, k)), raising=False)
    args = SimpleNamespace(guest=False, guest_port=8792, guest_token=None, guest_tunnel="cloudflared", token="admin-secret")
    assert cli._start_guest_if_enabled(object(), args) is None
    assert calls == []


def test_cli_guest_activation_generates_distinct_capability_token(monkeypatch):
    captured = {}

    class Handle:
        def close(self):
            pass

    def activate(port, **kwargs):
        captured.update(kwargs)
        return Handle()

    monkeypatch.setattr(guest_server, "activate", activate, raising=False)
    args = SimpleNamespace(guest=True, guest_port=8792, guest_token=None, guest_tunnel="cloudflared", token="admin-secret")
    handle = cli._start_guest_if_enabled(object(), args)
    assert handle is not None
    assert captured["http_port"] == 8792
    assert captured["tunnel"] == "cloudflared"
    assert isinstance(captured["guest_token"], str) and len(captured["guest_token"]) >= 24
    assert captured["guest_token"] != args.token


def test_cli_guest_activation_honors_explicit_guest_token(monkeypatch):
    captured = {}
    token = "viewer-only-capability-0123456789"
    monkeypatch.setattr(guest_server, "activate", lambda port, **kwargs: captured.update(kwargs) or object(), raising=False)
    args = SimpleNamespace(guest=True, guest_port=9002, guest_token=token, guest_tunnel="none", token="different-admin-token")
    cli._start_guest_if_enabled(object(), args)
    assert captured == {"http_port": 9002, "guest_token": token, "tunnel": "none"}


def test_share_url_contains_only_public_tunnel_and_guest_capability():
    token = "viewer-only-capability-0123456789"
    url = guest_server.share_url("https://example.trycloudflare.com", token)
    assert url == f"https://example.trycloudflare.com/g/{token}/"
    assert "admin" not in url.lower()


def test_guest_access_handle_closes_guest_server_and_tunnel():
    calls = []

    class Server:
        def shutdown(self): calls.append("shutdown")
        def server_close(self): calls.append("server_close")

    class Thread:
        def join(self, timeout): calls.append(("join", timeout))

    class Tunnel:
        def poll(self): return None
        def terminate(self): calls.append("terminate")

    handle = guest_server.GuestAccessHandle(Server(), Thread(), Tunnel(), "tok", None)
    handle.close()
    assert calls == ["shutdown", "server_close", ("join", 5), "terminate"]

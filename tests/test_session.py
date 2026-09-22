"""Tests del inicio de sesión en src.session (sin red: http.post simulado)."""

import pytest
import requests

from src.session import TSRSession


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_login_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = TSRSession()
    payload = {
        "data": {
            "login": {
                "member": {"MemberID": 42, "session": {"SessionId": "abc"}},
                "need_verify": False,
            }
        }
    }
    monkeypatch.setattr(session.http, "post", lambda *a, **k: _FakeResponse(payload))

    assert session.login("user@example.com", "secret") is None
    assert session.authenticated
    assert session.member_id == "42"
    assert session.login_key == "abc"


def test_login_reports_server_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    session = TSRSession()
    payload = {"errors": [{"message": "credenciales inválidas"}]}
    monkeypatch.setattr(session.http, "post", lambda *a, **k: _FakeResponse(payload))

    assert session.login("user@example.com", "wrong") == "credenciales inválidas"
    assert not session.authenticated


def test_login_reports_need_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    session = TSRSession()
    payload = {"data": {"login": {"need_verify": True}}}
    monkeypatch.setattr(session.http, "post", lambda *a, **k: _FakeResponse(payload))

    error = session.login("user@example.com", "secret")
    assert error is not None
    assert "verificación" in error
    assert not session.authenticated


def test_login_reports_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = TSRSession()

    def boom(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(session.http, "post", boom)

    error = session.login("user@example.com", "secret")
    assert error is not None
    assert "sin conexión" in error
    assert not session.authenticated

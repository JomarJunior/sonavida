"""`ModelMoraClient`: loopback only (Principle V); absence is lived as `starting`, not
a crash (FR-029); a successful exchange resolves to a `ModelResult`."""

from __future__ import annotations

import httpx
import pytest

from sonavida.ports.models import Busy, ModelMoraClient, ModelResult, Starting

REQUEST_ID = "11111111-1111-4111-8111-111111111111"


def test_refuses_a_non_loopback_host() -> None:
    with pytest.raises(ValueError, match="Principle V"):
        ModelMoraClient("http://museum.example.com:8431", "token")


async def test_modelmora_absent_is_starting_not_a_crash() -> None:
    """No real socket is ever opened (the suite's `no_network` fixture would fail
    loudly if one were); this simulates "nothing answers on loopback" purely with a
    transport that raises, exactly what httpx raises for a refused connection."""

    def _refuse_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(_refuse_connection)
    client = ModelMoraClient("http://127.0.0.1:8431", "token", transport=transport)
    try:
        outcome = await client.text("hello")
        assert isinstance(outcome, Starting)
        outcome = await client.image("a harbor", size=(512, 512))
        assert isinstance(outcome, Starting)
    finally:
        await client.aclose()


async def test_a_successful_exchange_resolves_to_a_result() -> None:
    def _respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/modelmora/v1/requests" and request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "requestId": REQUEST_ID,
                    "position": 0,
                    "estimatedWaitSeconds": 0,
                    "model": {"name": "a-text-model", "version": "1"},
                },
            )
        if request.url.path == f"/modelmora/v1/requests/{REQUEST_ID}":
            return httpx.Response(
                200,
                json={
                    "requestId": REQUEST_ID,
                    "state": "done",
                    "result": {
                        "model": {"name": "a-text-model", "version": "1"},
                        "text": "a plain reply",
                        "imageAvailable": False,
                        "settingsUsed": {"seed": 1},
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(_respond)
    client = ModelMoraClient("http://127.0.0.1:8431", "token", transport=transport)
    try:
        outcome = await client.text("hello")
    finally:
        await client.aclose()
    assert isinstance(outcome, ModelResult)
    assert outcome.text == "a plain reply"


async def test_a_busy_refusal_is_not_confused_with_absence() -> None:
    def _busy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"reason": "busy", "retryAfterSeconds": 30})

    transport = httpx.MockTransport(_busy)
    client = ModelMoraClient("http://127.0.0.1:8431", "token", transport=transport)
    try:
        outcome = await client.text("hello")
    finally:
        await client.aclose()
    assert isinstance(outcome, Busy)

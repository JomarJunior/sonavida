"""The `Models` port and the loopback client to **🧠 ModelMora** (ports.md, R-1, R-7).

Every answer the Studio's model server can give collapses to one of six typed
outcomes: a `Result`, or one of the ways the request did not run: `Busy`, `Starting`,
`Stopping`, `Failed`, `CannotServe`. `translate.py` turns those into the persona's
situations; nothing here decides what they mean to a persona.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class ModelResult:
    text: str | None
    image_bytes: bytes | None
    settings_used: dict[str, object]


@dataclass(frozen=True)
class Busy:
    retry_at: datetime | None = None


@dataclass(frozen=True)
class Starting:
    retry_at: datetime | None = None


@dataclass(frozen=True)
class Stopping:
    retry_at: datetime | None = None


@dataclass(frozen=True)
class Failed:
    pass


@dataclass(frozen=True)
class CannotServe:
    pass


ModelOutcome = ModelResult | Busy | Starting | Stopping | Failed | CannotServe


class Models(Protocol):
    async def text(
        self,
        instructions: str,
        *,
        conversation: tuple[dict[str, str], ...] = (),
        images: tuple[dict[str, str], ...] = (),
    ) -> ModelOutcome: ...

    async def image(
        self,
        description: str,
        *,
        avoid: str | None = None,
        size: tuple[int, int] = (1024, 1024),
    ) -> ModelOutcome: ...


def _refusal_outcome(reason: str, detail: dict[str, object]) -> ModelOutcome:
    retry_after = detail.get("retryAfterSeconds")
    retry_at = (
        datetime.now(UTC) + timedelta(seconds=float(retry_after))
        if isinstance(retry_after, int | float)
        else None
    )
    if reason == "busy":
        return Busy(retry_at)
    if reason == "starting":
        return Starting(retry_at)
    if reason == "stopping":
        return Stopping(retry_at)
    if reason == "failed_during_generation":
        return Failed()
    # unknown_model, model_unavailable, invalid_request, cannot_be_served_on_this_studio
    return CannotServe()


class ModelMoraClient:
    """The Studio's own client for **🧠 ModelMora**, over loopback HTTP only (Principle V)."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 40.0,
    ) -> None:
        host = urlsplit(base_url).hostname
        if transport is None and host not in _LOOPBACK_HOSTS:
            raise ValueError(
                f"refusing to reach ModelMora at non-loopback host {host!r} (Principle V)"
            )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def text(
        self,
        instructions: str,
        *,
        conversation: tuple[dict[str, str], ...] = (),
        images: tuple[dict[str, str], ...] = (),
    ) -> ModelOutcome:
        body: dict[str, object] = {"kind": "text", "instructions": instructions}
        if conversation:
            body["conversation"] = list(conversation)
        if images:
            body["images"] = list(images)
        return await self._run(body)

    async def image(
        self,
        description: str,
        *,
        avoid: str | None = None,
        size: tuple[int, int] = (1024, 1024),
    ) -> ModelOutcome:
        body: dict[str, object] = {
            "kind": "image",
            "description": description,
            "size": {"width": size[0], "height": size[1]},
        }
        if avoid:
            body["avoid"] = avoid
        return await self._run(body)

    async def _run(self, body: dict[str, object]) -> ModelOutcome:
        submitted = await self._client.post("/modelmora/v1/requests", json=body)
        if submitted.status_code >= 400:
            payload = submitted.json()
            return _refusal_outcome(payload["reason"], payload)
        request_id = submitted.json()["requestId"]
        while True:
            status = await self._client.get(
                f"/modelmora/v1/requests/{request_id}", params={"waitSeconds": 30}
            )
            if status.status_code >= 400:
                payload = status.json()
                return _refusal_outcome(payload["reason"], payload)
            data = status.json()
            state = data["state"]
            if state == "done":
                result = data["result"]
                image_bytes = None
                if result.get("imageAvailable"):
                    image = await self._client.get(f"/modelmora/v1/requests/{request_id}/image")
                    image_bytes = image.content
                return ModelResult(
                    text=result.get("text"),
                    image_bytes=image_bytes,
                    settings_used=result["settingsUsed"],
                )
            if state == "failed":
                return Failed()
            if state in ("stopped_before_completion", "withdrawn"):
                return Stopping()
            # waiting or running: the long poll above already spent up to 30s; ask again.

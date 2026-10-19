"""Authenticated server-to-server transport. No Discord or Hub credentials reach users."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import aiohttp


class HubError(Exception):
    pass


class HubBridge:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, key: str) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "hub-api"}):
            raise ValueError("HUB_API_URL must use HTTPS (HTTP is allowed only for local/internal development)")
        if not key:
            raise ValueError("HUB_BRIDGE_KEY is required")
        self.session = session
        self.base_url = base_url.rstrip("/") + "/api/daily-discord/bridge"
        self.headers = {"Authorization": f"Bearer {key}"}

    async def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            async with self.session.request(method, self.base_url + path, json=payload, headers=self.headers, allow_redirects=False) as response:
                data = await response.json()
                if not isinstance(data, dict):
                    raise HubError("O Hub retornou uma resposta inválida. Tente novamente.")
                if not response.ok:
                    message = data.get("message") or data.get("error")
                    if not isinstance(message, str):
                        message = "Não foi possível concluir no Hub. Confira sua conta e tente novamente."
                    raise HubError(message[:500])
                return data
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise HubError("Não consegui me comunicar com o Hub. Seu formulário não foi confirmado; tente novamente.") from exc

    async def project(self, project_id: str, action: str, payload: dict) -> dict:
        return await self.request("POST", f"/projects/{project_id}/{action}", payload)

    @classmethod
    def from_environment(cls, session: aiohttp.ClientSession) -> HubBridge:
        return cls(session, os.environ["HUB_API_URL"], os.environ["HUB_BRIDGE_KEY"])

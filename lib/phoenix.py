from __future__ import annotations

from typing import Any, Dict

import httpx


class PhoenixError(Exception):
    pass


class PhoenixClient:
    def __init__(self, base_url: str, password: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.password = password
        self._auth = ("", password)

    async def create_invoice(self, amount_sats: int, description: str) -> Dict[str, Any]:
        payload = {
            "amountSat": str(amount_sats),
            "description": description,
        }
        return await self._request("POST", "/createinvoice", data=payload)

    async def get_incoming_payment(self, payment_hash: str) -> Dict[str, Any]:
        return await self._request("GET", f"/payments/incoming/{payment_hash}")

    async def get_balance(self) -> Dict[str, Any]:
        return await self._request("GET", "/getbalance")

    async def pay_invoice(self, bolt11: str) -> Dict[str, Any]:
        return await self._request("POST", "/payinvoice", data={"invoice": bolt11})

    async def _request(
        self, method: str, path: str, data: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.request(method, url, auth=self._auth, data=data)
        except httpx.HTTPError as exc:
            raise PhoenixError(f"phoenix request failed: {exc}") from exc

        if response.status_code >= 400:
            raise PhoenixError(
                f"phoenix returned {response.status_code}: {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as exc:
            raise PhoenixError("phoenix returned non-json response") from exc

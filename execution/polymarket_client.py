# execution/polymarket_client.py
"""Minimal Polymarket CLOB adapter for tiny live-probe orders.

The rest of the bot remains dry-run by default. This adapter is only
constructed when ENABLE_LIVE_TRADING=true. Imports are intentionally lazy so
normal dry runs do not fail if py-clob-client is not installed/configured.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


class PolymarketLiveClient:
    """Thin wrapper around py-clob-client for buy-limit probes and cancels."""

    def __init__(self):
        try:
            from py_clob_client.client import ClobClient
        except Exception as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "py-clob-client is required for live probe mode. "
                "Run: pip install -r requirements.txt"
            ) from exc

        host = os.getenv("POLY_HOST", "https://clob.polymarket.com").strip()
        key = os.getenv("POLY_PRIVATE_KEY", "").strip()
        chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
        funder = os.getenv("POLY_FUNDER", "").strip() or None
        signature_type_raw = os.getenv("POLY_SIGNATURE_TYPE", "").strip()

        if not key:
            raise RuntimeError("POLY_PRIVATE_KEY missing; refusing live probe mode")

        kwargs: Dict[str, Any] = {"key": key, "chain_id": chain_id}
        if funder:
            kwargs["funder"] = funder
        if signature_type_raw:
            kwargs["signature_type"] = int(signature_type_raw)

        self.client = ClobClient(host, **kwargs)

        # Authenticated endpoints need API credentials. This is the standard
        # py-clob-client flow for deriving or creating them from the private key.
        creds = self.client.create_or_derive_api_creds()
        self.client.set_api_creds(creds)

    def buy_limit(self, token_id: str, price: float, size: float) -> Dict[str, Any]:
        """Submit a BUY limit order. Returns the exchange response dict."""
        try:
            from py_clob_client.clob_types import OrderArgs
            from py_clob_client.order_builder.constants import BUY
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("Could not import py-clob-client order types") from exc

        args = OrderArgs(
            price=round(float(price), 3),
            size=round(float(size), 2),
            side=BUY,
            token_id=str(token_id),
        )
        signed_order = self.client.create_order(args)
        resp = self.client.post_order(signed_order)
        return resp if isinstance(resp, dict) else {"raw_response": resp}

    def cancel(self, order_id: str) -> Dict[str, Any]:
        resp = self.client.cancel(str(order_id))
        return resp if isinstance(resp, dict) else {"raw_response": resp}

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = self.client.get_order(str(order_id))
            return resp if isinstance(resp, dict) else {"raw_response": resp}
        except Exception:
            return None

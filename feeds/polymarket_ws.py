# feeds/polymarket_ws.py
import time
import json
import asyncio
import websockets
import aiohttp
from pathlib import Path
from typing import Dict, Any, List, Optional


class PolyMarketBook:
    def __init__(
        self,
        asset_ids: List[str],
        raw_log_path: str = "dota_poly_bot/storage/pm_unknown_events.jsonl",
        snapshot_interval_s: float = 120.0,
        validation_tolerance: float = 0.01,
    ):
        self.asset_ids = [str(a) for a in asset_ids]
        self._raw_books: Dict[str, Dict[str, Dict[float, float]]] = {
            aid: {"bids": {}, "asks": {}} for aid in self.asset_ids
        }
        self.books: Dict[str, Dict[str, Any]] = {}
        self.url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        self.raw_log_path = Path(raw_log_path)
        self.snapshot_interval_s = snapshot_interval_s
        self.validation_tolerance = validation_tolerance
        self._last_snapshot_s: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def run(self):
        while True:
            try:
                await self.refresh_snapshots()
                async with websockets.connect(self.url, ping_interval=10, ping_timeout=10) as ws:
                    sub = {"assets_ids": self.asset_ids, "type": "market"}
                    await ws.send(json.dumps(sub))
                    print(f"Polymarket WS subscribed to {len(self.asset_ids)} assets")

                    async for msg in ws:
                        if time.time() - self._last_snapshot_s >= self.snapshot_interval_s:
                            await self.refresh_snapshots()
                        event = json.loads(msg)
                        self.handle_event(event)

            except Exception as e:
                print(f"Polymarket WS error: {e}")
                await asyncio.sleep(1)

    async def refresh_snapshots(self):
        """Seed/reconcile local books from CLOB REST `/book` and warn on mismatch."""
        self._last_snapshot_s = time.time()
        try:
            session = await self._get_session()
            for asset_id in self.asset_ids:
                try:
                    async with session.get("https://clob.polymarket.com/book", params={"token_id": asset_id}) as r:
                        if r.status != 200:
                            continue
                        data = await r.json()
                    if isinstance(data, dict):
                        data.setdefault("asset_id", asset_id)
                        rest_metrics = self._metrics_from_book_payload(data)
                        local = self.books.get(asset_id)
                        if local and rest_metrics:
                            bid_diff = abs(float(local.get("best_bid", 0)) - float(rest_metrics.get("best_bid", 0)))
                            ask_diff = abs(float(local.get("best_ask", 1)) - float(rest_metrics.get("best_ask", 1)))
                            if bid_diff > self.validation_tolerance or ask_diff > self.validation_tolerance:
                                print(
                                    f"PM BOOK VALIDATION RESET token={asset_id[:10]}... "
                                    f"local=({local.get('best_bid')},{local.get('best_ask')}) "
                                    f"rest=({rest_metrics.get('best_bid')},{rest_metrics.get('best_ask')})"
                                )
                        self._process_book_update(data, int(time.time() * 1000))
                except Exception as e:
                    print(f"PM snapshot refresh failed for {asset_id[:10]}...: {e}")
                    continue
        except Exception as e:
            print(f"PM snapshot refresh failed: {e}")

    def _metrics_from_book_payload(self, data: Dict[str, Any]) -> Optional[Dict[str, float]]:
        bids = data.get("bids", []) or []
        asks = data.get("asks", []) or []
        try:
            bid_prices = [float(x["price"]) for x in bids if float(x.get("size", 0)) > 0]
            ask_prices = [float(x["price"]) for x in asks if float(x.get("size", 0)) > 0]
            best_bid = max(bid_prices) if bid_prices else 0.001
            best_ask = min(ask_prices) if ask_prices else 0.999
            return {"best_bid": best_bid, "best_ask": best_ask}
        except Exception:
            return None

    def _log_unknown(self, event: Any):
        try:
            self.raw_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.raw_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts_ms": int(time.time() * 1000), "event": event}) + "\n")
        except Exception:
            pass

    def handle_event(self, event: Any):
        ts_ms = int(time.time() * 1000)

        if isinstance(event, list):
            for item in event:
                self.handle_event(item)
            return

        if not isinstance(event, dict):
            self._log_unknown(event)
            return

        if "price_changes" in event:
            for pc in event.get("price_changes", []):
                self._process_price_change(pc, ts_ms)
            return

        event_type = event.get("event_type") or event.get("type")
        if event_type == "book" or ("bids" in event and "asks" in event):
            self._process_book_update(event, ts_ms)
            return

        if event_type in ("last_trade_price", "tick_size_change", "market_resolved"):
            return

        self._log_unknown(event)
        print(f"UNKNOWN PM EVENT logged: {event_type or list(event.keys())}")

    def _get_asset_id(self, data: Dict[str, Any]) -> Optional[str]:
        return str(data.get("asset_id") or data.get("assetId") or data.get("token_id") or data.get("tokenId") or "") or None

    def _process_book_update(self, data: Dict[str, Any], ts_ms: int):
        asset_id = self._get_asset_id(data)
        if not asset_id or asset_id not in self.asset_ids:
            return

        bids = data.get("bids", []) or []
        asks = data.get("asks", []) or []
        self._raw_books[asset_id]["bids"] = {
            float(x["price"]): float(x["size"])
            for x in bids
            if float(x.get("price", 0)) > 0 and float(x.get("size", 0)) > 0
        }
        self._raw_books[asset_id]["asks"] = {
            float(x["price"]): float(x["size"])
            for x in asks
            if float(x.get("price", 0)) > 0 and float(x.get("size", 0)) > 0
        }
        self._update_best_metrics(asset_id, ts_ms)

    def _process_price_change(self, data: Dict[str, Any], ts_ms: int):
        asset_id = self._get_asset_id(data)
        if not asset_id or asset_id not in self.asset_ids:
            return

        side_raw = str(data.get("side", "")).upper()
        side = "bids" if side_raw in ("BUY", "BID", "BIDS") else "asks"
        try:
            price = float(data.get("price", 0))
            size = float(data.get("size", 0))
        except Exception:
            return

        if price <= 0:
            return

        if size <= 0:
            self._raw_books[asset_id][side].pop(price, None)
        else:
            self._raw_books[asset_id][side][price] = size

        self._update_best_metrics(asset_id, ts_ms)

    def _update_best_metrics(self, asset_id: str, ts_ms: int):
        bids = self._raw_books[asset_id]["bids"]
        asks = self._raw_books[asset_id]["asks"]

        if not bids and not asks:
            return

        best_bid = max(bids.keys()) if bids else 0.001
        best_ask = min(asks.keys()) if asks else 0.999
        sorted_bids = sorted(bids.items(), key=lambda x: x[0], reverse=True)
        sorted_asks = sorted(asks.items(), key=lambda x: x[0])

        self.books[asset_id] = {
            "ts_ms": ts_ms,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": (best_bid + best_ask) / 2,
            "spread": best_ask - best_bid,
            "bid_depth": sum(x[1] for x in sorted_bids[:5]),
            "ask_depth": sum(x[1] for x in sorted_asks[:5]),
        }

    def get_book(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self.books.get(str(asset_id))

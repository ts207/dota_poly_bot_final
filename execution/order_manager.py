# execution/order_manager.py
import os
import time
import asyncio
from typing import Callable, Dict, Any, Optional, Tuple


BookProvider = Callable[[str], Optional[Dict[str, Any]]]


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return default


def _first_float(data: Dict[str, Any], keys: Tuple[str, ...], default: Optional[float] = None) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except Exception:
            continue
    return default


class OrderManager:
    """Dry-run logger plus opt-in tiny-capital live probe mode.

    Live mode logs every important exchange interaction into `live_order_events`:
    submit, pre-cancel status, cancel response, post-cancel status, failures, and
    fill snapshots at configurable delays.
    """

    def __init__(
        self,
        poly_client: Optional[Any],
        dry_run: bool = True,
        db: Optional[Any] = None,
        market_id: str = "",
        book_provider: Optional[BookProvider] = None,
    ):
        self.client = poly_client
        self.dry_run = dry_run
        self.db = db
        self.market_id = market_id
        self.book_provider = book_provider

        self.open_orders: Dict[str, Dict[str, Any]] = {}
        self.dry_exposure_by_token: Dict[str, float] = {}

        self.enable_live = _env_bool("ENABLE_LIVE_TRADING", False)
        self.live_probe_only = _env_bool("LIVE_PROBE_ONLY", True)
        self.live_max_order_size = _env_float("LIVE_MAX_ORDER_SIZE", 1.00)
        self.live_max_position_per_match = _env_float("LIVE_MAX_POSITION_PER_MATCH", 5.00)
        self.live_max_orders_per_match = _env_int("LIVE_MAX_ORDERS_PER_MATCH", 5)
        self.live_filled_exposure = 0.0
        self.live_orders_sent = 0
        self._observed_filled_by_order: Dict[str, float] = {}

    def get_open_exposure(self) -> float:
        if self.dry_run:
            return sum(float(o.get("size", 0.0)) for o in self.open_orders.values())
        open_size = sum(float(o.get("size", 0.0)) for o in self.open_orders.values())
        return self.live_filled_exposure + open_size

    def get_token_exposure(self, token_id: str) -> float:
        return float(self.dry_exposure_by_token.get(token_id, 0.0))

    def _live_safety_check(self, price: float, size: float) -> None:
        if not self.enable_live:
            raise RuntimeError("LIVE_BLOCKED: ENABLE_LIVE_TRADING=false")
        if not self.live_probe_only:
            raise RuntimeError("LIVE_BLOCKED: LIVE_PROBE_ONLY must remain true")
        if self.client is None:
            raise RuntimeError("LIVE_BLOCKED: Polymarket client is not configured")
        if price <= 0 or price >= 1:
            raise RuntimeError(f"LIVE_BLOCKED: invalid price {price}")
        if size <= 0:
            raise RuntimeError("LIVE_BLOCKED: size <= 0")
        if size > self.live_max_order_size:
            raise RuntimeError(
                f"LIVE_BLOCKED: size {size} > LIVE_MAX_ORDER_SIZE {self.live_max_order_size}"
            )
        if self.live_orders_sent >= self.live_max_orders_per_match:
            raise RuntimeError("LIVE_BLOCKED: LIVE_MAX_ORDERS_PER_MATCH reached")
        if self.get_open_exposure() + size > self.live_max_position_per_match:
            raise RuntimeError("LIVE_BLOCKED: LIVE_MAX_POSITION_PER_MATCH reached")

    def _extract_order_state(self, payload: Any, intended_size: float) -> Dict[str, Optional[float]]:
        if not isinstance(payload, dict):
            return {"filled_size": None, "avg_fill_price": None, "remaining_size": None}

        filled_size = _first_float(payload, (
            "filled_size", "filledSize", "size_matched", "sizeMatched",
            "matched_size", "matchedSize", "filled", "filledAmount",
        ), default=0.0)
        # Do NOT use a generic "price" field here: most order/status payloads
        # use it for the limit price, not the actual average fill price.
        avg_fill_price = _first_float(payload, (
            "avg_price", "average_price", "avgPrice", "averageFillPrice",
            "fill_price", "fillPrice", "matched_price", "matchedPrice",
        ), default=None)
        remaining_size = _first_float(payload, (
            "remaining_size", "remainingSize", "unfilled_size", "unfilledSize", "size_remaining",
        ), default=None)
        if remaining_size is None and filled_size is not None:
            remaining_size = max(0.0, float(intended_size) - float(filled_size))

        return {
            "filled_size": filled_size,
            "avg_fill_price": avg_fill_price,
            "remaining_size": remaining_size,
        }

    def _log_live_event(
        self,
        *,
        event_type: str,
        order: Dict[str, Any],
        exchange_order_id: Optional[str] = None,
        ack_ms: Optional[int] = None,
        raw_response: Any = None,
        fill_ts_ms: Optional[int] = None,
        infer_order_state: bool = True,
    ) -> None:
        if not self.db:
            return
        if infer_order_state:
            state = self._extract_order_state(raw_response, float(order.get("size", 0.0)))
        else:
            state = {"filled_size": None, "avg_fill_price": None, "remaining_size": None}
        self.db.log_live_order_event(
            event_type=event_type,
            market_id=self.market_id,
            token_id=order.get("token_id", ""),
            exchange_order_id=exchange_order_id or order.get("id"),
            signal_id=order.get("signal_id"),
            intended_price=order.get("price"),
            intended_size=order.get("size"),
            filled_size=state.get("filled_size"),
            avg_fill_price=state.get("avg_fill_price"),
            remaining_size=state.get("remaining_size"),
            ack_ms=ack_ms,
            fill_ts_ms=fill_ts_ms,
            raw_response=raw_response,
        )

    def _write_fill_snapshot_now(
        self,
        order: Dict[str, Any],
        exchange_order_id: str,
        seconds_after_fill: float,
    ) -> None:
        """Write a fill snapshot synchronously.

        The 0-second snapshot must not be fire-and-forget; otherwise it can be
        lost if the process is stopped right after a fill is detected.
        """
        if not self.db or not self.book_provider:
            return
        try:
            book = self.book_provider(order["token_id"])
            if book:
                self.db.log_live_fill_snapshot(
                    exchange_order_id=exchange_order_id,
                    signal_id=order.get("signal_id"),
                    market_id=self.market_id,
                    token_id=order["token_id"],
                    seconds_after_fill=seconds_after_fill,
                    book=book,
                )
        except Exception as e:
            print(f"LIVE FILL SNAPSHOT ERROR: {e}")

    async def _snapshot_after_fill(self, order: Dict[str, Any], exchange_order_id: str, seconds_after_fill: float) -> None:
        if seconds_after_fill > 0:
            await asyncio.sleep(seconds_after_fill)
        self._write_fill_snapshot_now(order, exchange_order_id, seconds_after_fill)

    def _maybe_schedule_fill_snapshots(self, order: Dict[str, Any], exchange_order_id: str, payload: Any) -> None:
        state = self._extract_order_state(payload, float(order.get("size", 0.0)))
        filled_size = float(state.get("filled_size") or 0.0)
        previous = self._observed_filled_by_order.get(exchange_order_id, 0.0)
        if filled_size <= previous:
            return

        self.live_filled_exposure += max(0.0, filled_size - previous)
        self._observed_filled_by_order[exchange_order_id] = filled_size
        fill_ts_ms = int(time.time() * 1000)
        self._log_live_event(
            event_type="FILL_DETECTED",
            order=order,
            exchange_order_id=exchange_order_id,
            raw_response=payload,
            fill_ts_ms=fill_ts_ms,
        )

        raw_offsets = os.getenv("LIVE_FILL_SNAPSHOT_OFFSETS_S", "0,5,15,30,60")
        for raw in raw_offsets.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                offset = float(raw)
            except Exception:
                continue
            if offset <= 0:
                self._write_fill_snapshot_now(order, exchange_order_id, 0.0)
            else:
                asyncio.create_task(self._snapshot_after_fill(order, exchange_order_id, offset))

    async def buy_limit(
        self,
        token_id: str,
        price: float,
        size: float,
        signal: Dict[str, Any],
        signal_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        order = {
            "token_id": str(token_id),
            "side": "BUY",
            "price": round(float(price), 3),
            "size": round(float(size), 2),
            "signal": signal,
            "signal_id": signal_id,
            "ts_ms": int(time.time() * 1000),
        }

        if self.dry_run:
            order_id = f"dry-{order['ts_ms']}-{len(self.open_orders)}"
            order["id"] = order_id
            print(f"DRY ORDER: {order}")
            if self.db:
                self.db.log_order(
                    market_id=self.market_id,
                    token_id=token_id,
                    side="BUY",
                    price=order["price"],
                    size=order["size"],
                    status="DRY_SENT",
                    signal_id=signal_id,
                )
            self.open_orders[order_id] = order
            self.dry_exposure_by_token[token_id] = self.dry_exposure_by_token.get(token_id, 0.0) + order["size"]
            return {"id": order_id, "status": "simulated"}

        try:
            self._live_safety_check(order["price"], order["size"])
            submit_ts = int(time.time() * 1000)
            resp = self.client.buy_limit(order["token_id"], order["price"], order["size"])
            ack_ts = int(time.time() * 1000)

            order_id = (
                resp.get("orderID")
                or resp.get("order_id")
                or resp.get("orderId")
                or resp.get("id")
            ) if isinstance(resp, dict) else None
            if not order_id:
                raise RuntimeError(f"LIVE_ORDER_NO_ID: {resp}")

            exchange_order_id = str(order_id)
            order["id"] = exchange_order_id
            order["ack_ms"] = ack_ts - submit_ts
            order["exchange_response"] = resp
            self.open_orders[exchange_order_id] = order
            self.live_orders_sent += 1

            print(f"LIVE PROBE ORDER: {order}")
            if self.db:
                self.db.log_order(
                    market_id=self.market_id,
                    token_id=token_id,
                    side="BUY",
                    price=order["price"],
                    size=order["size"],
                    status="LIVE_SENT",
                    signal_id=signal_id,
                    ack_ms=order["ack_ms"],
                    exchange_order_id=exchange_order_id,
                    raw_response=resp,
                )
            self._log_live_event(
                event_type="SUBMIT_ACK",
                order=order,
                exchange_order_id=exchange_order_id,
                ack_ms=order["ack_ms"],
                raw_response=resp,
            )
            self._maybe_schedule_fill_snapshots(order, exchange_order_id, resp)
            return {"id": exchange_order_id, "status": "live_sent", "response": resp}
        except Exception as e:
            print(f"LIVE ORDER BLOCKED/FAILED: {e}")
            if self.db:
                self.db.log_order(
                    self.market_id,
                    token_id,
                    "BUY",
                    order["price"],
                    order["size"],
                    "LIVE_FAILED",
                    signal_id,
                    raw_response={"error": str(e)},
                )
                self.db.log_live_order_event(
                    event_type="SUBMIT_FAILED",
                    market_id=self.market_id,
                    token_id=token_id,
                    signal_id=signal_id,
                    intended_price=order["price"],
                    intended_size=order["size"],
                    raw_response={"error": str(e)},
                )
            return {"id": "error", "status": "failed", "error": str(e)}

    async def cancel_after(self, order_id: str, seconds: float = 2.0):
        await asyncio.sleep(seconds)
        if order_id == "error":
            return

        if self.dry_run:
            order = self.open_orders.pop(order_id, None)
            if order:
                token_id = order["token_id"]
                self.dry_exposure_by_token[token_id] = max(
                    0.0,
                    self.dry_exposure_by_token.get(token_id, 0.0) - float(order.get("size", 0.0)),
                )
                print(f"DRY CANCEL: {order_id}")
            return

        order = self.open_orders.pop(order_id, None)
        if not order:
            return

        try:
            before = self.client.get_order(order_id) if self.client else None
            self._log_live_event(event_type="PRE_CANCEL_STATUS", order=order, exchange_order_id=order_id, raw_response=before)
            self._maybe_schedule_fill_snapshots(order, order_id, before)

            cancel_start = int(time.time() * 1000)
            resp = self.client.cancel(order_id) if self.client else None
            cancel_ack_ms = int(time.time() * 1000) - cancel_start
            self._log_live_event(
                event_type="CANCEL_ACK",
                order=order,
                exchange_order_id=order_id,
                ack_ms=cancel_ack_ms,
                raw_response=resp,
                infer_order_state=False,
            )

            after = self.client.get_order(order_id) if self.client else None
            self._log_live_event(event_type="POST_CANCEL_STATUS", order=order, exchange_order_id=order_id, raw_response=after)
            self._maybe_schedule_fill_snapshots(order, order_id, after)

            final_state = self._extract_order_state(after or before or {}, float(order.get("size", 0.0)))
            print(f"LIVE CANCEL: order_id={order_id} before={before} resp={resp} after={after}")
            if self.db:
                self.db.log_order(
                    market_id=self.market_id,
                    token_id=order["token_id"],
                    side="BUY",
                    price=order["price"],
                    size=order["size"],
                    status="LIVE_CANCELLED",
                    signal_id=order.get("signal_id"),
                    fill_price=final_state.get("avg_fill_price"),
                    filled_size=final_state.get("filled_size"),
                    exchange_order_id=order_id,
                    cancel_ack_ms=cancel_ack_ms,
                    raw_response={"before": before, "cancel": resp, "after": after},
                )
        except Exception as e:
            print(f"LIVE CANCEL ERROR: {e}")
            if self.db:
                self.db.log_live_order_event(
                    event_type="CANCEL_FAILED",
                    market_id=self.market_id,
                    token_id=order.get("token_id", ""),
                    exchange_order_id=order_id,
                    signal_id=order.get("signal_id"),
                    intended_price=order.get("price"),
                    intended_size=order.get("size"),
                    raw_response={"error": str(e)},
                )

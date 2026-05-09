# execution/order_manager.py
import time
import asyncio
from typing import Dict, Any, Optional


class OrderManager:
    def __init__(self, poly_client: Optional[Any], dry_run: bool = True, db: Optional[Any] = None, market_id: str = ""):
        self.client = poly_client
        self.dry_run = dry_run
        self.db = db
        self.market_id = market_id
        self.open_orders: Dict[str, Dict[str, Any]] = {}
        self.dry_exposure_by_token: Dict[str, float] = {}

    def get_open_exposure(self) -> float:
        return sum(float(o.get("size", 0.0)) for o in self.open_orders.values())

    def get_token_exposure(self, token_id: str) -> float:
        return float(self.dry_exposure_by_token.get(token_id, 0.0))

    async def buy_limit(
        self,
        token_id: str,
        price: float,
        size: float,
        signal: Dict[str, Any],
        signal_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        order = {
            "token_id": token_id,
            "side": "BUY",
            "price": round(price, 3),
            "size": round(size, 2),
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
            # Real execution placeholder. Keep dry_run=True until paper-traded.
            print("Real execution not implemented; keep dry_run=True.")
            if self.db:
                self.db.log_order(self.market_id, token_id, "BUY", order["price"], order["size"], "UNIMPLEMENTED", signal_id)
            return {"id": "error", "status": "unimplemented"}
        except Exception as e:
            print(f"Order error: {e}")
            if self.db:
                self.db.log_order(self.market_id, token_id, "BUY", order["price"], order["size"], "FAILED", signal_id)
            return {"id": "error", "status": "failed"}

    async def cancel_after(self, order_id: str, seconds: float = 2.0):
        await asyncio.sleep(seconds)

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

        try:
            # self.client.cancel_order(order_id)
            self.open_orders.pop(order_id, None)
        except Exception as e:
            print(f"Cancel error: {e}")

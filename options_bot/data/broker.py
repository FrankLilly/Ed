"""Broker integration — order execution for paper and live trading."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime

from options_bot.models import OptionLeg, OrderAction, PositionSide, TradeOrder

logger = logging.getLogger(__name__)


class Broker(ABC):
    """Abstract broker interface for order execution."""

    @abstractmethod
    def get_account_balance(self) -> float:
        """Get current account buying power / cash."""

    @abstractmethod
    def submit_order(self, order: TradeOrder) -> str:
        """Submit an order, returns order ID."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""

    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        """Get status of an order (filled, pending, cancelled, etc.)."""

    @abstractmethod
    def close_position(self, position_id: str) -> bool:
        """Close an existing position."""


class AlpacaBroker(Broker):
    """Alpaca broker for paper and live options trading."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.base_url = (
            "https://paper-api.alpaca.markets" if paper
            else "https://api.alpaca.markets"
        )

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        import urllib.request

        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def get_account_balance(self) -> float:
        account = self._request("GET", "/v2/account")
        return float(account.get("buying_power", 0))

    def submit_order(self, order: TradeOrder) -> str:
        """Submit a multi-leg options order to Alpaca."""
        legs_payload = []
        for leg in order.legs:
            c = leg.contract
            # Build OCC symbol: SYMBOL + YYMMDD + C/P + Strike*1000
            exp_str = c.expiration.strftime("%y%m%d")
            opt_char = "C" if c.option_type.value == "call" else "P"
            strike_str = f"{int(c.strike * 1000):08d}"
            occ_symbol = f"{c.symbol:<6}{exp_str}{opt_char}{strike_str}"

            side = "buy" if leg.side == PositionSide.LONG else "sell"

            legs_payload.append({
                "symbol": occ_symbol,
                "qty": str(leg.quantity),
                "side": side,
                "type": "limit",
                "limit_price": str(round(c.mid_price, 2)),
            })

        if len(legs_payload) == 1:
            payload = {
                "symbol": legs_payload[0]["symbol"],
                "qty": legs_payload[0]["qty"],
                "side": legs_payload[0]["side"],
                "type": "limit",
                "time_in_force": "day",
                "limit_price": legs_payload[0]["limit_price"],
                "order_class": "simple",
            }
        else:
            payload = {
                "order_class": "mleg",
                "legs": legs_payload,
                "time_in_force": "day",
            }

        logger.info("Submitting order: %s", json.dumps(payload, indent=2))
        result = self._request("POST", "/v2/orders", payload)
        order_id = result.get("id", "unknown")
        logger.info("Order submitted: %s", order_id)
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._request("DELETE", f"/v2/orders/{order_id}")
            return True
        except Exception:
            logger.exception("Failed to cancel order %s", order_id)
            return False

    def get_order_status(self, order_id: str) -> str:
        result = self._request("GET", f"/v2/orders/{order_id}")
        return result.get("status", "unknown")

    def close_position(self, position_id: str) -> bool:
        try:
            self._request("DELETE", f"/v2/positions/{position_id}")
            return True
        except Exception:
            logger.exception("Failed to close position %s", position_id)
            return False


class PaperBroker(Broker):
    """In-memory paper broker for testing without any API calls."""

    def __init__(self, starting_balance: float = 100_000.0) -> None:
        self.balance = starting_balance
        self._orders: dict[str, dict] = {}
        self._next_id = 1

    def get_account_balance(self) -> float:
        return self.balance

    def submit_order(self, order: TradeOrder) -> str:
        order_id = f"paper-{self._next_id:04d}"
        self._next_id += 1

        cost = order.net_premium  # negative = debit, positive = credit
        self.balance += cost

        self._orders[order_id] = {
            "status": "filled",
            "strategy": order.strategy_name,
            "premium": cost,
            "timestamp": datetime.now().isoformat(),
            "legs": len(order.legs),
        }

        logger.info(
            "Paper order %s filled: %s, premium=%.2f, balance=%.2f",
            order_id, order.strategy_name, cost, self.balance,
        )
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "cancelled"
            return True
        return False

    def get_order_status(self, order_id: str) -> str:
        if order_id in self._orders:
            return self._orders[order_id]["status"]
        return "not_found"

    def close_position(self, position_id: str) -> bool:
        logger.info("Paper close position: %s", position_id)
        return True

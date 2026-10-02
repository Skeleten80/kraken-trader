"""Paper trading portfolio priced off live Kraken market data.

No real money moves. Market orders fill immediately at the supplied price;
limit orders sit in `pending` until `update_limits()` sees the market touch
their price. An optional taker/maker fee keeps the accounting honest.
"""
from __future__ import annotations

import json
import time
import uuid


class PaperTradeError(Exception):
    """Invalid paper trade (insufficient funds, unknown order, ...)."""


def _now() -> int:
    return int(time.time())


class PaperPortfolio:
    def __init__(
        self,
        starting_cash: float = 10_000.0,
        quote: str = "USD",
        fee_rate: float = 0.0026,
        state: dict | None = None,
    ):
        self.quote = quote
        self.fee_rate = fee_rate
        if state is None:
            self.starting_cash = float(starting_cash)
            self.cash = float(starting_cash)
            self.positions: dict[str, float] = {}  # base asset code -> amount
            self.pending: list[dict] = []  # open limit orders
            self.history: list[dict] = []  # every fill, newest last
        else:
            self.starting_cash = state["starting_cash"]
            self.cash = state["cash"]
            self.positions = dict(state["positions"])
            self.pending = list(state["pending"])
            self.history = list(state["history"])

    # -- market orders -----------------------------------------------------
    def market_buy(self, pair_key: str, base_asset: str, quote_amount: float, price: float) -> dict:
        """Spend `quote_amount` of cash on the base asset at `price`."""
        if quote_amount <= 0:
            raise PaperTradeError("quote_amount must be positive")
        fee = quote_amount * self.fee_rate
        total = quote_amount + fee
        if total > self.cash + 1e-9:
            raise PaperTradeError(
                f"insufficient {self.quote}: need {total:.2f}, have {self.cash:.2f}"
            )
        volume = quote_amount / price
        self.cash -= total
        self.positions[base_asset] = self.positions.get(base_asset, 0.0) + volume
        return self._record_fill(pair_key, base_asset, "buy", volume, price, fee)

    def market_sell(self, pair_key: str, base_asset: str, volume: float, price: float) -> dict:
        """Sell `volume` of the base asset at `price`."""
        if volume <= 0:
            raise PaperTradeError("volume must be positive")
        held = self.positions.get(base_asset, 0.0)
        if volume > held + 1e-12:
            raise PaperTradeError(f"insufficient {base_asset}: need {volume}, have {held}")
        proceeds = volume * price
        fee = proceeds * self.fee_rate
        self.cash += proceeds - fee
        self.positions[base_asset] = held - volume
        if self.positions[base_asset] < 1e-12:
            del self.positions[base_asset]
        return self._record_fill(pair_key, base_asset, "sell", volume, price, fee)

    # -- limit orders ------------------------------------------------------
    def limit_order(
        self, pair_key: str, base_asset: str, side: str, volume: float, price: float
    ) -> str:
        """Stage a limit order. It fills when update_limits() sees the touch."""
        if side not in ("buy", "sell"):
            raise PaperTradeError("side must be 'buy' or 'sell'")
        if volume <= 0 or price <= 0:
            raise PaperTradeError("volume and price must be positive")
        if side == "buy":
            need = volume * price * (1 + self.fee_rate)
            if need > self.cash + 1e-9:
                raise PaperTradeError(
                    f"insufficient {self.quote} to stage buy: need {need:.2f}"
                )
        else:
            held = self.positions.get(base_asset, 0.0)
            if volume > held + 1e-12:
                raise PaperTradeError(f"insufficient {base_asset} to stage sell")
        order_id = uuid.uuid4().hex[:8]
        self.pending.append(
            {
                "id": order_id,
                "pair": pair_key,
                "base": base_asset,
                "side": side,
                "volume": volume,
                "price": price,
                "created": _now(),
            }
        )
        return order_id

    def cancel_order(self, order_id: str) -> dict:
        for i, order in enumerate(self.pending):
            if order["id"] == order_id:
                return self.pending.pop(i)
        raise PaperTradeError(f"no pending order {order_id!r}")

    def update_limits(self, last_prices: dict[str, float]) -> list[dict]:
        """Fill any pending limit orders touched by current `last` prices.

        `last_prices` maps pair_key -> last trade price. Returns the fills.
        """
        fills: list[dict] = []
        still_pending: list[dict] = []
        for order in self.pending:
            last = last_prices.get(order["pair"])
            touched = last is not None and (
                (order["side"] == "buy" and last <= order["price"])
                or (order["side"] == "sell" and last >= order["price"])
            )
            if not touched:
                still_pending.append(order)
                continue
            try:
                if order["side"] == "buy":
                    fill = self.market_buy(
                        order["pair"], order["base"], order["volume"] * order["price"], order["price"]
                    )
                else:
                    fill = self.market_sell(
                        order["pair"], order["base"], order["volume"], order["price"]
                    )
                fill["order_id"] = order["id"]
                fill["limit"] = True
                fills.append(fill)
            except PaperTradeError:
                # Funds moved since staging; keep the order open.
                still_pending.append(order)
        self.pending = still_pending
        return fills

    # -- valuation ---------------------------------------------------------
    def value(self, last_prices: dict[str, float]) -> float:
        """Total equity in quote currency at current prices."""
        total = self.cash
        pair_for_base = {o["base"]: o["pair"] for o in self.pending}
        # map base asset -> pair via pending orders or history
        for fill in self.history:
            pair_for_base.setdefault(fill["base"], fill["pair"])
        for base, amount in self.positions.items():
            pair = pair_for_base.get(base)
            price = last_prices.get(pair) if pair else None
            if price is not None:
                total += amount * price
        return total

    def pnl(self, last_prices: dict[str, float]) -> float:
        return self.value(last_prices) - self.starting_cash

    def summary(self, last_prices: dict[str, float]) -> dict:
        return {
            "cash": self.cash,
            "quote": self.quote,
            "positions": dict(self.positions),
            "pending_orders": len(self.pending),
            "total_value": self.value(last_prices),
            "pnl": self.pnl(last_prices),
            "trades": len(self.history),
        }

    # -- persistence -------------------------------------------------------
    def _record_fill(self, pair_key, base_asset, side, volume, price, fee) -> dict:
        fill = {
            "time": _now(),
            "pair": pair_key,
            "base": base_asset,
            "side": side,
            "volume": volume,
            "price": price,
            "fee": fee,
        }
        self.history.append(fill)
        return fill

    def to_dict(self) -> dict:
        return {
            "starting_cash": self.starting_cash,
            "cash": self.cash,
            "quote": self.quote,
            "fee_rate": self.fee_rate,
            "positions": self.positions,
            "pending": self.pending,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, state: dict) -> "PaperPortfolio":
        portfolio = cls(state=state)
        portfolio.quote = state.get("quote", "USD")
        portfolio.fee_rate = state.get("fee_rate", 0.0026)
        return portfolio

    def save(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "PaperPortfolio":
        with open(path) as fh:
            return cls.from_dict(json.load(fh))

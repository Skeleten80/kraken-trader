"""Demo strategy: SMA-crossover paper trading on XBT/USD hourly candles.

Pure example — not financial advice, not a profitable strategy. It shows how
to wire market data -> signal -> paper portfolio. Run:

    python examples/sma_watcher.py            # print signal only
    python examples/sma_watcher.py --trade     # execute one paper trade
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kraken_trader import public
from kraken_trader.paper import PaperPortfolio, PaperTradeError

PAIR = "BTC/USD"
STATE = os.path.expanduser("~/.kraken-paper.json")
FAST = 10
SLOW = 30


def sma(values: list[float], window: int) -> float:
    return sum(values[-window:]) / window


def main() -> int:
    parser = argparse.ArgumentParser(description="SMA crossover paper-trading demo")
    parser.add_argument("--trade", action="store_true",
                        help="execute the signal as one paper trade")
    args = parser.parse_args()

    candles = public.get_ohlc(PAIR, interval=60)
    closes = [c["close"] for c in candles]
    if len(closes) < SLOW + 1:
        print("not enough candle history", file=sys.stderr)
        return 1

    fast_now, slow_now = sma(closes, FAST), sma(closes, SLOW)
    fast_prev, slow_prev = sma(closes[:-1], FAST), sma(closes[:-1], SLOW)
    last = closes[-1]

    signal = "hold"
    if fast_prev <= slow_prev and fast_now > slow_now:
        signal = "buy"
    elif fast_prev >= slow_prev and fast_now < slow_now:
        signal = "sell"

    print(f"XBT/USD hourly  SMA{FAST}={fast_now:,.2f}  SMA{SLOW}={slow_now:,.2f}")
    print(f"last {last:,.2f}  -> signal: {signal}")

    if not args.trade or signal == "hold":
        return 0

    portfolio = PaperPortfolio.load(STATE) if os.path.exists(STATE) else PaperPortfolio()
    key = public.resolve_pair(PAIR)
    base, _ = public.pair_assets(PAIR)
    try:
        if signal == "buy":
            fill = portfolio.market_buy(key, base, quote_amount=500.0, price=last)
            print(f"paper-bought {fill['volume']:.8f} XBT @ {last:,.2f}")
        else:
            held = portfolio.positions.get(base, 0.0)
            if held <= 0:
                print("signal is sell but nothing held; no trade")
                return 0
            fill = portfolio.market_sell(key, base, volume=held, price=last)
            print(f"paper-sold {fill['volume']:.8f} XBT @ {last:,.2f}")
    except PaperTradeError as exc:
        print(f"paper trade failed: {exc}", file=sys.stderr)
        return 1
    portfolio.save(STATE)
    return 0


if __name__ == "__main__":
    sys.exit(main())

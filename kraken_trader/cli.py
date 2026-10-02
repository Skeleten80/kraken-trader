"""Command line interface: market data + paper trading on Kraken public data."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

from . import public
from .paper import PaperPortfolio, PaperTradeError

DEFAULT_STATE = os.path.expanduser("~/.kraken-paper.json")


def _load_portfolio(path: str) -> PaperPortfolio:
    if os.path.exists(path):
        return PaperPortfolio.load(path)
    return PaperPortfolio()


def _save_portfolio(portfolio: PaperPortfolio, path: str) -> None:
    portfolio.save(path)


def _price_map(pairs: list[str]) -> dict[str, float]:
    """pair_key -> last price, one batched ticker call."""
    keys = [public.resolve_pair(p) for p in pairs]
    tickers = public.get_ticker(pairs)
    out = {}
    for requested, key in zip(pairs, keys):
        display = next(iter(tickers)) if len(tickers) == 1 else None
        # get_ticker keys are display pairs; map back via resolve
        for disp, quote in tickers.items():
            if public.resolve_pair(disp) == key:
                out[key] = quote["last"]
                break
    return out


def _all_traded_pairs(portfolio: PaperPortfolio) -> list[str]:
    pairs = set()
    for base in portfolio.positions:
        for src in portfolio.history + portfolio.pending:
            if src.get("base") == base:
                pairs.add(src["pair"])
                break
    for order in portfolio.pending:
        pairs.add(order["pair"])
    return sorted(pairs)


def cmd_price(args: argparse.Namespace) -> int:
    try:
        tickers = public.get_ticker(args.pairs)
    except public.KrakenPublicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for pair, q in tickers.items():
        change = (q["last"] - q["open_24h"]) / q["open_24h"] * 100 if q["open_24h"] else 0
        print(f"{pair}")
        print(f"  last   {q['last']:,.2f}")
        print(f"  bid    {q['bid']:,.2f}   ask {q['ask']:,.2f}")
        print(f"  24h    {q['low_24h']:,.2f} - {q['high_24h']:,.2f}  ({change:+.2f}%)")
        print(f"  volume {q['volume_24h']:,.2f}")
    return 0


def cmd_book(args: argparse.Namespace) -> int:
    try:
        book = public.get_orderbook(args.pair, count=args.count)
    except public.KrakenPublicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"asks (sell orders, lowest first):")
    for price, vol in book["asks"][: args.count]:
        print(f"  {price:>14,.2f}  x {vol:.6f}")
    print(f"bids (buy orders, highest first):")
    for price, vol in book["bids"][: args.count]:
        print(f"  {price:>14,.2f}  x {vol:.6f}")
    return 0


def cmd_ohlc(args: argparse.Namespace) -> int:
    try:
        candles = public.get_ohlc(args.pair, interval=args.interval)
    except public.KrakenPublicError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for c in candles[-args.limit :]:
        ts = datetime.fromtimestamp(c["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(
            f"{ts}  o {c['open']:>12,.2f}  h {c['high']:>12,.2f}  "
            f"l {c['low']:>12,.2f}  c {c['close']:>12,.2f}  v {c['volume']:.4f}"
        )
    return 0


def _trade(args: argparse.Namespace, kind: str) -> int:
    portfolio = _load_portfolio(args.state)
    try:
        key = public.resolve_pair(args.pair)
        base, quote = public.pair_assets(args.pair)
        last = _price_map([args.pair])[key]
        fills = portfolio.update_limits({key: last})
        for f in fills:
            print(f"limit order {f['order_id']} filled: {f['side']} {f['volume']:.8f} @ {f['price']:,.2f}")
        if kind == "buy":
            fill = portfolio.market_buy(key, base, args.amount, last)
            print(f"bought {fill['volume']:.8f} {public.prettify_asset(base)} @ {last:,.2f} "
                  f"(fee {fill['fee']:.2f} {portfolio.quote})")
        elif kind == "sell":
            fill = portfolio.market_sell(key, base, args.amount, last)
            print(f"sold {fill['volume']:.8f} {public.prettify_asset(base)} @ {last:,.2f} "
                  f"(fee {fill['fee']:.2f} {portfolio.quote})")
        else:  # limit
            order_id = portfolio.limit_order(key, base, args.side, args.amount, args.price)
            print(f"limit {args.side} staged: {args.amount} {public.prettify_asset(base)} "
                  f"@ {args.price:,.2f}  (id {order_id})")
    except (public.KrakenPublicError, PaperTradeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _save_portfolio(portfolio, args.state)
    return 0


def cmd_portfolio(args: argparse.Namespace) -> int:
    portfolio = _load_portfolio(args.state)
    pairs = _all_traded_pairs(portfolio)
    prices: dict[str, float] = {}
    if pairs:
        try:
            # resolve_pair needs user-style input; pair keys are already keys,
            # so fetch tickers via a display-pair round trip
            displays = []
            for key in pairs:
                info = public.get_asset_pairs()[key]
                displays.append(
                    f"{public.prettify_asset(info['base'])}/{public.prettify_asset(info['quote'])}"
                )
            prices = _price_map(displays)
        except public.KrakenPublicError as exc:
            print(f"warning: live prices unavailable ({exc}); showing cash only",
                  file=sys.stderr)
    s = portfolio.summary(prices)
    print(f"cash:      {s['cash']:>12,.2f} {s['quote']}")
    for base, amount in s["positions"].items():
        pair = next((o["pair"] for o in portfolio.history + portfolio.pending
                     if o.get("base") == base), None)
        px = prices.get(pair) if pair else None
        val = f"{amount * px:>12,.2f}" if px else "       n/a"
        print(f"{public.prettify_asset(base):<10} {amount:>14,.8f}  value {val}")
    if portfolio.pending:
        print("pending limit orders:")
        for o in portfolio.pending:
            print(f"  {o['id']}  {o['side']} {o['volume']} {public.prettify_asset(o['base'])}"
                  f" @ {o['price']:,.2f}")
    print(f"equity:    {s['total_value']:>12,.2f} {s['quote']}")
    print(f"P&L:       {s['pnl']:>+12,.2f} {s['quote']}  ({len(portfolio.history)} fills)")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    portfolio = _load_portfolio(args.state)
    for f in portfolio.history[-args.limit :]:
        ts = datetime.fromtimestamp(f["time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        tag = "limit" if f.get("limit") else "market"
        print(f"{ts}  {f['side']:<4} {f['volume']:.8f} {public.prettify_asset(f['base'])}"
              f" @ {f['price']:,.2f}  fee {f['fee']:.2f}  [{tag}]")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if os.path.exists(args.state):
        os.remove(args.state)
    print(f"paper portfolio reset (was {args.state})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kraken-paper",
        description="Kraken market data and paper trading (no real money).",
    )
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help="path to paper portfolio file")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("price", help="show ticker for one or more pairs")
    p.add_argument("pairs", nargs="+", help='e.g. BTC/USD ETH/USD')
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("book", help="show order book top levels")
    p.add_argument("pair", help='e.g. BTC/USD')
    p.add_argument("--count", type=int, default=10)
    p.set_defaults(func=cmd_book)

    p = sub.add_parser("ohlc", help="show recent OHLC candles")
    p.add_argument("pair", help='e.g. BTC/USD')
    p.add_argument("--interval", type=int, default=60, help="candle minutes")
    p.add_argument("--limit", type=int, default=10, help="candles to show")
    p.set_defaults(func=cmd_ohlc)

    p = sub.add_parser("buy", help="paper market-buy with quote currency")
    p.add_argument("pair", help='e.g. BTC/USD')
    p.add_argument("amount", type=float, help="how much quote currency to spend")
    p.set_defaults(func=lambda a: _trade(a, "buy"))

    p = sub.add_parser("sell", help="paper market-sell a base amount")
    p.add_argument("pair", help='e.g. BTC/USD')
    p.add_argument("amount", type=float, help="how much base asset to sell")
    p.set_defaults(func=lambda a: _trade(a, "sell"))

    p = sub.add_parser("limit", help="stage a paper limit order")
    p.add_argument("side", choices=["buy", "sell"])
    p.add_argument("pair", help='e.g. BTC/USD')
    p.add_argument("amount", type=float, help="base asset amount")
    p.add_argument("price", type=float, help="limit price")
    p.set_defaults(func=lambda a: _trade(a, "limit"))

    p = sub.add_parser("portfolio", help="show paper portfolio and P&L")
    p.set_defaults(func=cmd_portfolio)

    p = sub.add_parser("history", help="show fill history")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("reset", help="wipe the paper portfolio")
    p.set_defaults(func=cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

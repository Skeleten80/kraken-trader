# kraken-trader

Paper-trading toolkit on Kraken's **public** market data. No API key, no real
money — prices are live, the portfolio is simulated.

Built as the safe starting point for a Kraken trading project while account
access is unavailable. Live trading gets wired in later, behind explicit
per-trade approval.

## Layout

```
kraken_trader/
  public.py   # read-only Kraken REST client (ticker, OHLC, order book)
  paper.py    # paper portfolio: market/limit orders, fees, P&L, JSON persistence
  cli.py      # `kraken-paper` command line interface
tests/
  test_public.py  # live public-API tests
  test_paper.py   # deterministic portfolio tests (no network)
examples/
  sma_watcher.py  # demo SMA-crossover strategy on paper
```

## Quickstart

```bash
pip install -r requirements.txt

# market data (no key needed)
python -m kraken_trader.cli price BTC/USD ETH/USD
python -m kraken_trader.cli book BTC/USD --count 5
python -m kraken_trader.cli ohlc BTC/USD --interval 60 --limit 5

# paper trading ($10,000 virtual USD, state in ~/.kraken-paper.json)
python -m kraken_trader.cli buy BTC/USD 500      # spend $500 at market
python -m kraken_trader.cli limit buy BTC/USD 0.01 60000
python -m kraken_trader.cli portfolio
python -m kraken_trader.cli history
python -m kraken_trader.cli sell BTC/USD 0.005
python -m kraken_trader.cli reset                # wipe the paper portfolio
```

Run the tests:

```bash
pip install pytest
python -m pytest tests/ -q
```

Try the demo strategy:

```bash
python examples/sma_watcher.py            # prints the current signal
python examples/sma_watcher.py --trade    # executes one paper trade
```

## Notes

- Pair names are flexible: `BTC/USD`, `btcusd`, and `XBTUSD` all work.
  (Kraken calls Bitcoin XBT internally.)
- Paper fills are idealized: market orders fill instantly at the last price,
  limit orders fill when the last price touches. A 0.26% taker fee is applied
  by default, matching Kraken's typical tier.
- Nothing here is financial advice, and paper profits prove nothing about
  live trading.

## Going live (later)

Real trading needs a Kraken API key with **trading permissions**, created at
Settings → API on a signed-in session. The plan when account access is back:

1. Start with a **read-only** key (query funds/orders) to validate the
   connection and the HMAC-SHA512 request signing.
2. Add a trading key only when there's a strategy worth running.
3. Every live order goes through explicit human approval — no autonomous
   trading.

## Non-goals

- No autonomous trading loop. No leverage/margin/futures. No "profitable
  strategy" claims.

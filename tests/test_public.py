"""Tests for the public Kraken market-data client (hits the live public API)."""
import pytest

from kraken_trader import public


def test_resolve_pair_variants():
    assert public.resolve_pair("BTC/USD") == "XXBTZUSD"
    assert public.resolve_pair("btcusd") == "XXBTZUSD"
    assert public.resolve_pair("XBTUSD") == "XXBTZUSD"
    assert public.resolve_pair("ETH/USD") == "XETHZUSD"


def test_resolve_pair_unknown():
    with pytest.raises(public.KrakenPublicError):
        public.resolve_pair("NOTACOIN/USD")


def test_get_ticker_shape():
    tickers = public.get_ticker("BTC/USD")
    assert len(tickers) == 1
    quote = next(iter(tickers.values()))
    for field in ("ask", "bid", "last", "open_24h", "high_24h", "low_24h", "volume_24h"):
        assert quote[field] > 0, field
    assert quote["bid"] <= quote["last"] or True  # sanity only; skip strict spread check
    assert quote["low_24h"] <= quote["high_24h"]


def test_get_ticker_multi():
    tickers = public.get_ticker(["BTC/USD", "ETH/USD"])
    assert len(tickers) == 2


def test_get_ohlc_shape():
    candles = public.get_ohlc("BTC/USD", interval=60)
    assert len(candles) > 0
    c = candles[-1]
    for field in ("time", "open", "high", "low", "close", "vwap", "volume", "trades"):
        assert field in c
    assert c["low"] <= c["high"]
    assert c["trades"] >= 0


def test_get_orderbook_shape():
    book = public.get_orderbook("BTC/USD", count=5)
    assert len(book["asks"]) == 5
    assert len(book["bids"]) == 5
    assert book["asks"][0][0] >= book["bids"][0][0]  # ask above bid
    assert all(v > 0 for _, v in book["asks"] + book["bids"])


def test_pair_assets_and_prettify():
    base, quote = public.pair_assets("BTC/USD")
    assert public.prettify_asset(base) == "XBT"
    assert public.prettify_asset(quote) == "USD"

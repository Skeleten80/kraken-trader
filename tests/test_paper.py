"""Tests for the paper-trading portfolio (no network; prices are injected)."""
import pytest

from kraken_trader.paper import PaperPortfolio, PaperTradeError

PAIR = "XXBTZUSD"
BASE = "XXBT"


def make_portfolio(**kwargs):
    kwargs.setdefault("fee_rate", 0.0)  # deterministic math in tests
    return PaperPortfolio(starting_cash=10_000.0, **kwargs)


def test_market_buy_and_sell():
    p = make_portfolio()
    fill = p.market_buy(PAIR, BASE, quote_amount=6_000.0, price=60_000.0)
    assert fill["volume"] == pytest.approx(0.1)
    assert p.cash == pytest.approx(4_000.0)
    assert p.positions[BASE] == pytest.approx(0.1)

    fill = p.market_sell(PAIR, BASE, volume=0.05, price=70_000.0)
    assert p.cash == pytest.approx(4_000.0 + 3_500.0)
    assert p.positions[BASE] == pytest.approx(0.05)


def test_insufficient_funds_and_holdings():
    p = make_portfolio()
    with pytest.raises(PaperTradeError):
        p.market_buy(PAIR, BASE, quote_amount=99_999.0, price=60_000.0)
    with pytest.raises(PaperTradeError):
        p.market_sell(PAIR, BASE, volume=1.0, price=60_000.0)


def test_value_and_pnl():
    p = make_portfolio()
    p.market_buy(PAIR, BASE, quote_amount=6_000.0, price=60_000.0)
    assert p.value({PAIR: 60_000.0}) == pytest.approx(10_000.0)
    assert p.value({PAIR: 70_000.0}) == pytest.approx(11_000.0)
    assert p.pnl({PAIR: 70_000.0}) == pytest.approx(1_000.0)


def test_limit_buy_fills_on_touch():
    p = make_portfolio()
    order_id = p.limit_order(PAIR, BASE, "buy", volume=0.1, price=55_000.0)
    assert len(p.pending) == 1
    # market above the limit: no fill
    assert p.update_limits({PAIR: 60_000.0}) == []
    assert len(p.pending) == 1
    # market touches the limit: fills
    fills = p.update_limits({PAIR: 54_000.0})
    assert len(fills) == 1
    assert fills[0]["order_id"] == order_id
    assert fills[0]["limit"] is True
    assert p.positions[BASE] == pytest.approx(0.1)
    assert len(p.pending) == 0


def test_limit_sell_fills_on_touch():
    p = make_portfolio()
    p.market_buy(PAIR, BASE, quote_amount=6_000.0, price=60_000.0)
    p.limit_order(PAIR, BASE, "sell", volume=0.1, price=70_000.0)
    assert p.update_limits({PAIR: 65_000.0}) == []
    fills = p.update_limits({PAIR: 70_000.0})
    assert len(fills) == 1
    assert BASE not in p.positions
    assert p.cash == pytest.approx(4_000.0 + 7_000.0)


def test_cancel_order():
    p = make_portfolio()
    order_id = p.limit_order(PAIR, BASE, "buy", volume=0.1, price=55_000.0)
    cancelled = p.cancel_order(order_id)
    assert cancelled["id"] == order_id
    assert p.pending == []
    with pytest.raises(PaperTradeError):
        p.cancel_order("nope")


def test_fee_accounting():
    p = PaperPortfolio(starting_cash=10_000.0, fee_rate=0.01)
    p.market_buy(PAIR, BASE, quote_amount=1_000.0, price=50_000.0)
    assert p.cash == pytest.approx(10_000.0 - 1_010.0)  # 1% fee on the spend


def test_save_load_roundtrip(tmp_path):
    p = make_portfolio()
    p.market_buy(PAIR, BASE, quote_amount=6_000.0, price=60_000.0)
    p.limit_order(PAIR, BASE, "sell", volume=0.05, price=70_000.0)
    path = str(tmp_path / "paper.json")
    p.save(path)
    q = PaperPortfolio.load(path)
    assert q.cash == pytest.approx(p.cash)
    assert q.positions == p.positions
    assert len(q.pending) == 1
    assert len(q.history) == 1
    assert q.starting_cash == p.starting_cash

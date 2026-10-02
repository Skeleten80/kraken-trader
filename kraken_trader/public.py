"""Read-only access to Kraken's public market data.

No API key required. Every function raises KrakenPublicError on API errors.
Pair input is flexible: "BTC/USD", "btcusd", "XBTUSD" all resolve to the same
Kraken pair.
"""
from __future__ import annotations

import requests

BASE_URL = "https://api.kraken.com"
API_PATH = "/0/public"

# Shorthands users type -> Kraken's internal asset codes.
_ASSET_ALIASES = {
    "BTC": "XBT",
    "DOGE": "XDG",  # Kraken lists Dogecoin as XXDG
}

_pair_key_cache: dict[str, str] = {}
_asset_pairs_cache: dict | None = None
_assets_cache: dict | None = None


class KrakenPublicError(Exception):
    """Kraken returned an error payload or the request failed."""


def _request(endpoint: str, params: dict | None = None, timeout: int = 15) -> dict:
    try:
        resp = requests.get(
            f"{BASE_URL}{API_PATH}/{endpoint}", params=params or {}, timeout=timeout
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise KrakenPublicError(f"HTTP error talking to Kraken: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise KrakenPublicError(f"Kraken returned a non-JSON response: {exc}") from exc
    errors = payload.get("error") or []
    if errors:
        raise KrakenPublicError("; ".join(errors))
    return payload["result"]


def get_asset_pairs() -> dict:
    """Raw AssetPairs result, cached for the process lifetime."""
    global _asset_pairs_cache
    if _asset_pairs_cache is None:
        _asset_pairs_cache = _request("AssetPairs")
    return _asset_pairs_cache


def get_assets() -> dict:
    """Raw Assets result (asset code -> info incl. altname), cached."""
    global _assets_cache
    if _assets_cache is None:
        _assets_cache = _request("Assets")
    return _assets_cache


def resolve_pair(pair: str) -> str:
    """Turn user input like 'BTC/USD' into Kraken's REST pair key.

    Example: 'BTC/USD' -> 'XXBTZUSD'.
    """
    if pair in _pair_key_cache:
        return _pair_key_cache[pair]
    cleaned = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    for alias, code in _ASSET_ALIASES.items():
        if cleaned.startswith(alias):
            cleaned = code + cleaned[len(alias):]
            break
    pairs = get_asset_pairs()
    for key, info in pairs.items():
        altname = (info.get("altname") or "").replace("/", "")
        wsname = (info.get("wsname") or "").replace("/", "")
        if key.upper() == cleaned or altname.upper() == cleaned or wsname.upper() == cleaned:
            _pair_key_cache[pair] = key
            return key
    raise KrakenPublicError(f"Unknown trading pair: {pair!r}")


def pair_assets(pair: str) -> tuple[str, str]:
    """Return (base_code, quote_code), e.g. ('XXBT', 'ZUSD') for 'BTC/USD'."""
    info = get_asset_pairs()[resolve_pair(pair)]
    return info["base"], info["quote"]


def prettify_asset(code: str) -> str:
    """Turn an internal asset code into its display name: 'XXBT' -> 'XBT'."""
    assets = get_assets()
    if code in assets:
        return assets[code].get("altname", code)
    return code


def _display_pair(pair: str) -> str:
    base, quote = pair_assets(pair)
    return f"{prettify_asset(base)}/{prettify_asset(quote)}"


def get_ticker(pairs: str | list[str]) -> dict[str, dict]:
    """Current ticker for one or more pairs.

    Returns {display_pair: {ask, bid, last, open_24h, high_24h, low_24h, volume_24h}}.
    """
    if isinstance(pairs, str):
        pairs = [pairs]
    keys = [resolve_pair(p) for p in pairs]
    result = _request("Ticker", {"pair": ",".join(keys)})
    out: dict[str, dict] = {}
    for requested, key in zip(pairs, keys):
        raw = result[key]
        out[_display_pair(requested)] = {
            "ask": float(raw["a"][0]),
            "bid": float(raw["b"][0]),
            "last": float(raw["c"][0]),
            "open_24h": float(raw["o"]),
            "high_24h": float(raw["h"][1]),
            "low_24h": float(raw["l"][1]),
            "volume_24h": float(raw["v"][1]),
        }
    return out


def get_ohlc(pair: str, interval: int = 60) -> list[dict]:
    """OHLC candles for a pair. interval is minutes: 1, 5, 15, 30, 60, 240, 1440, ..."""
    result = _request("OHLC", {"pair": resolve_pair(pair), "interval": interval})
    key = next(k for k in result if k != "last")
    candles = []
    for row in result[key]:
        candles.append(
            {
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "vwap": float(row[5]),
                "volume": float(row[6]),
                "trades": int(row[7]),
            }
        )
    return candles


def get_orderbook(pair: str, count: int = 10) -> dict[str, list[tuple[float, float]]]:
    """Top of the order book: {'asks': [(price, volume), ...], 'bids': [...]}."""
    result = _request("Depth", {"pair": resolve_pair(pair), "count": count})
    key = next(iter(result))
    book = result[key]
    return {
        "asks": [(float(p), float(v)) for p, v, _ in book["asks"]],
        "bids": [(float(p), float(v)) for p, v, _ in book["bids"]],
    }

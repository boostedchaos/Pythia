"""CoinGecko simple/price — BTC, ETH and a gold proxy.

Verified 2026-08-28: docs/feed-verification.md#coingecko. Keyless public endpoint.

KIND is "snapshot": the instrument list is the full current state each fetch.

Plan §5.11 — identity is the SYMBOL, never the price. upstream_id is "BTC"; the
price lives only in extra["price"], and the title carries no number, so a quote
moving does not manufacture a new observation.

PAXG (PAX Gold) is a gold-backed token used here as a spot-gold PROXY, not a gold
fixing. It is labelled as a proxy in extra so a brief cannot present it as the
gold price. No equity index or oil source verified keyless — see the markets
coverage gap in docs/feed-verification.md.
"""
from __future__ import annotations

import json

from ..models import Observation
from . import _util

SOURCE_ID = "coingecko"
BEAT = "markets"
KIND = "snapshot"
DISPLAY_NAME = "CoinGecko spot prices"
CANONICAL_DOMAIN = "coingecko.com"

# coingecko id -> (symbol, display name, instrument kind)
INSTRUMENTS = {
    "bitcoin": ("BTC", "Bitcoin", "crypto"),
    "ethereum": ("ETH", "Ethereum", "crypto"),
    "pax-gold": ("PAXG", "PAX Gold (gold proxy)", "gold_proxy"),
}

URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    f"?ids={','.join(INSTRUMENTS)}"
    "&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true"
)

_PAGE = "https://www.coingecko.com/en/coins/{}"


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    out: list[Observation] = []
    received = 0
    for coin_id, (symbol, name, kind) in INSTRUMENTS.items():
        row = data.get(coin_id)
        if not isinstance(row, dict):
            continue
        received += 1
        price = row.get("usd")
        if price is None:
            continue
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=f"{name} ({symbol}/USD)",  # no price in the title — identity is the symbol
                url=_PAGE.format(coin_id),
                beat=BEAT,
                summary="",
                upstream_id=symbol,
                source_ts_ms=(int(row["last_updated_at"]) * 1000
                              if isinstance(row.get("last_updated_at"), (int, float)) else None),
                extra={
                    "price": price,
                    "currency": "USD",
                    "change_24h_pct": row.get("usd_24h_change"),
                    "symbol": symbol,
                    "instrument_kind": kind,
                },
            )
        )
    return out, received


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)

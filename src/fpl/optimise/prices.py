"""FPL selling prices. All prices are in tenths of £1m (61 = £6.1m)."""

from __future__ import annotations


def selling_price(purchase_price: int, now_cost: int) -> int:
    """You keep half of any rise, rounded down to 0.1m; you take the whole of any fall."""
    profit = now_cost - purchase_price
    if profit > 0:
        return purchase_price + profit // 2
    return now_cost

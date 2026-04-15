from __future__ import annotations

import argparse
import csv
import copy
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, DefaultDict, Dict, List, Optional, Tuple

from datamodel import Listing, Observation, Order, OrderDepth, Trade, TradingState

# Per-product position limits (adjust from the wiki for your round).
POSITION_LIMITS: Dict[str, int] = {
    "ASH_COATED_OSMIUM": 20,
    "INTARIAN_PEPPER_ROOT": 20,
}

DEFAULT_LIMIT = 20


def _parse_num(cell: str) -> Optional[float]:
    if cell is None:
        return None
    s = str(cell).strip()
    if not s:
        return None
    return float(s)


def row_to_order_depth(row: Dict[str, str]) -> OrderDepth:
    """Convert one prices_*.csv row to OrderDepth (asks stored as negative qty)."""
    buy_orders: Dict[int, int] = {}
    sell_orders: Dict[int, int] = {}
    for i in (1, 2, 3):
        bp = _parse_num(row.get(f"bid_price_{i}", ""))
        bv = _parse_num(row.get(f"bid_volume_{i}", ""))
        if bp is not None and bv is not None:
            buy_orders[int(round(bp))] = int(bv)
        ap = _parse_num(row.get(f"ask_price_{i}", ""))
        av = _parse_num(row.get(f"ask_volume_{i}", ""))
        if ap is not None and av is not None:
            sell_orders[int(round(ap))] = -int(av)
    return OrderDepth(buy_orders=buy_orders, sell_orders=sell_orders)


def load_prices_csv(path: str) -> Tuple[List[int], Dict[int, Dict[str, Dict[str, str]]]]:
    """Returns sorted timestamps and map timestamp -> product -> row dict."""
    by_ts: Dict[int, Dict[str, Dict[str, str]]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            ts = int(row["timestamp"])
            product = row["product"]
            by_ts[ts][product] = row
    timestamps = sorted(by_ts.keys())
    return timestamps, dict(by_ts)


def load_trades_csv(path: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            out.append(
                {
                    "timestamp": int(row["timestamp"]),
                    "symbol": row["symbol"],
                    "price": int(round(float(row["price"]))),
                    "quantity": int(float(row["quantity"])),
                    "buyer": row.get("buyer") or "",
                    "seller": row.get("seller") or "",
                }
            )
    out.sort(key=lambda r: r["timestamp"])
    return out


def trades_between(
    trades: List[Dict[str, Any]], t_open: int, t_close: int
) -> Dict[str, List[Trade]]:
    """Market trades with timestamp in (t_open, t_close]."""
    bucket: Dict[str, List[Trade]] = defaultdict(list)
    for tr in trades:
        if t_open < tr["timestamp"] <= t_close:
            bucket[tr["symbol"]].append(
                Trade(
                    symbol=tr["symbol"],
                    price=tr["price"],
                    quantity=tr["quantity"],
                    buyer=tr["buyer"],
                    seller=tr["seller"],
                    timestamp=tr["timestamp"],
                )
            )
    return dict(bucket)


def make_listings(products: List[str]) -> Dict[str, Listing]:
    return {
        p: Listing(symbol=p, product=p, denomination="XIRECS")
        for p in products
    }


def position_limit_for(product: str) -> int:
    return POSITION_LIMITS.get(product, DEFAULT_LIMIT)


def orders_pass_limits(
    position: Dict[str, int],
    orders_by_product: Dict[str, List[Order]],
) -> bool:
    for product, orders in orders_by_product.items():
        lim = position_limit_for(product)
        pos = position.get(product, 0)
        buy_sum = sum(o.quantity for o in orders if o.quantity > 0)
        sell_sum = sum(-o.quantity for o in orders if o.quantity < 0)
        if pos + buy_sum > lim:
            return False
        if pos - sell_sum < -lim:
            return False
    return True


def match_buy(book: OrderDepth, limit_price: int, qty: int, symbol: str, ts: int) -> Tuple[int, List[Trade], int]:
    """Return (qty_filled, trades, cash_delta). cash_delta = -sum(price*qty) for buyer."""
    remaining = qty
    trades: List[Trade] = []
    cash = 0
    # Ascending ask prices
    for price in sorted(book.sell_orders.keys()):
        if remaining <= 0:
            break
        if price > limit_price:
            break
        avail = -book.sell_orders[price]
        if avail <= 0:
            continue
        take = min(remaining, avail)
        trades.append(
            Trade(
                symbol=symbol,
                price=price,
                quantity=take,
                buyer="SUBMISSION",
                seller="",
                timestamp=ts,
            )
        )
        cash -= price * take
        book.sell_orders[price] += take  # negative qty moves toward 0
        if book.sell_orders[price] == 0:
            del book.sell_orders[price]
        remaining -= take
    filled = qty - remaining
    return filled, trades, cash


def match_sell(book: OrderDepth, limit_price: int, qty: int, symbol: str, ts: int) -> Tuple[int, List[Trade], int]:
    """qty is positive number of units to sell. Returns (filled, trades, cash_delta)."""
    remaining = qty
    trades: List[Trade] = []
    cash = 0
    for price in sorted(book.buy_orders.keys(), reverse=True):
        if remaining <= 0:
            break
        if price < limit_price:
            break
        avail = book.buy_orders[price]
        if avail <= 0:
            continue
        take = min(remaining, avail)
        trades.append(
            Trade(
                symbol=symbol,
                price=price,
                quantity=take,
                buyer="",
                seller="SUBMISSION",
                timestamp=ts,
            )
        )
        cash += price * take
        book.buy_orders[price] -= take
        if book.buy_orders[price] == 0:
            del book.buy_orders[price]
        remaining -= take
    filled = qty - remaining
    return filled, trades, cash


@dataclass
class BacktestResult:
    final_cash: float
    position: Dict[str, int]
    mark_to_mid: float
    equity: float
    iterations: int


def run_backtest(
    trader_factory: Callable[[], Any],
    prices_path: str,
    trades_path: Optional[str],
    max_steps: Optional[int] = None,
) -> BacktestResult:
    timestamps, by_ts = load_prices_csv(prices_path)
    trade_log = load_trades_csv(trades_path) if trades_path else []

    products = sorted({p for m in by_ts.values() for p in m})
    listings = make_listings(products)

    position: Dict[str, int] = {p: 0 for p in products}
    cash = 0.0
    trader_data = ""
    prev_ts = -1
    own_trades_last: Dict[str, List[Trade]] = {p: [] for p in products}
    last_ts_processed: Optional[int] = None

    steps = 0
    for ts in timestamps:
        if max_steps is not None and steps >= max_steps:
            break
        rows = by_ts[ts]
        order_depths: Dict[str, OrderDepth] = {}
        for p in products:
            if p not in rows:
                continue
            od = row_to_order_depth(rows[p])
            order_depths[p] = od

        market_trades = trades_between(trade_log, prev_ts, ts)
        obs = Observation()
        state = TradingState(
            traderData=trader_data,
            timestamp=ts,
            listings=listings,
            order_depths=order_depths,
            own_trades=own_trades_last,
            market_trades=market_trades,
            position=dict(position),
            observations=obs,
        )

        trader = trader_factory()
        out = trader.run(state)
        if not isinstance(out, tuple) or len(out) != 3:
            raise TypeError("Trader.run must return (result_dict, conversions, traderData)")
        result, conversions, trader_data = out
        if conversions is None:
            conversions = 0

        if conversions:
            # Round 1 local replay ignores conversions.
            pass

        orders_by_product: DefaultDict[str, List[Order]] = defaultdict(list)
        for sym, ords in result.items():
            orders_by_product[sym].extend(ords)

        own_trades_last = {p: [] for p in products}
        if not orders_pass_limits(position, dict(orders_by_product)):
            prev_ts = ts
            steps += 1
            continue

        for product in sorted(orders_by_product.keys()):
            book = copy.deepcopy(order_depths.get(product, OrderDepth()))
            for order in orders_by_product[product]:
                if order.quantity > 0:
                    filled, trs, d_cash = match_buy(
                        book, order.price, order.quantity, product, ts
                    )
                elif order.quantity < 0:
                    filled, trs, d_cash = match_sell(
                        book, order.price, -order.quantity, product, ts
                    )
                else:
                    continue
                cash += d_cash
                position[product] += filled if order.quantity > 0 else -filled
                own_trades_last[product].extend(trs)

        prev_ts = ts
        last_ts_processed = ts
        steps += 1

    mark = 0.0
    if last_ts_processed is None:
        last_rows: Dict[str, Dict[str, str]] = {}
    else:
        last_rows = by_ts[last_ts_processed]
    for p, q in position.items():
        if p in last_rows:
            mp = _parse_num(last_rows[p].get("mid_price", ""))
            if mp is not None:
                mark += q * mp
    equity = cash + mark
    return BacktestResult(
        final_cash=cash,
        position=dict(position),
        mark_to_mid=mark,
        equity=equity,
        iterations=steps,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Trader on Prosperity CSVs")
    parser.add_argument(
        "--prices",
        default="prices_round_1_day_0.csv",
        help="prices_round_*.csv path",
    )
    parser.add_argument(
        "--trades",
        default="trades_round_1_day_0.csv",
        help="trades_round_*.csv path (optional for market_trades in state)",
    )
    parser.add_argument("--max-steps", type=int, default=None)
    args = parser.parse_args()

    from trader_round1 import Trader

    res = run_backtest(
        Trader,
        prices_path=args.prices,
        trades_path=args.trades,
        max_steps=args.max_steps,
    )
    print(f"Iterations: {res.iterations}")
    print(f"Cash (approx, from matched trades): {res.final_cash:.2f}")
    print(f"Position: {res.position}")
    print(f"Mark-to-mid: {res.mark_to_mid:.2f}")
    print(f"Equity (cash + mid*pos): {res.equity:.2f}")


if __name__ == "__main__":
    main()

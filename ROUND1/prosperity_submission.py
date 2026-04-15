"""
Round 1 - Ash-coated Osmium & Intarian Pepper Root: short-horizon fade with
volatility + spread gates
"""

import json
import statistics
from typing import Any, Dict, List, Optional, Tuple

from datamodel import Order, OrderDepth, TradingState

POSITION_LIMIT = 20

K_SIGMA = 0.75
MIN_ABSOLUTE = 6
SPREAD_FRAC = 0.42

ROLLING_WINDOW = {
    "ASH_COATED_OSMIUM": 25,
    "INTARIAN_PEPPER_ROOT": 80,
}

MAX_ORDER_SIZE = 2
SOFT_CAP = 8
HARD_UNWIND = 13


def book_mid(od: OrderDepth) -> Optional[float]:
    if not od.buy_orders or not od.sell_orders:
        return None
    best_bid = max(od.buy_orders.keys())
    best_ask = min(od.sell_orders.keys())
    return (best_bid + best_ask) / 2.0


def quoted_spread(od: OrderDepth) -> Optional[int]:
    if not od.buy_orders or not od.sell_orders:
        return None
    return min(od.sell_orders.keys()) - max(od.buy_orders.keys())


class Trader:
    def bid(self) -> int:
        return 15

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}
        store: Dict[str, Any] = {}
        if state.traderData:
            try:
                store = json.loads(state.traderData)
            except json.JSONDecodeError:
                store = {}

        prev_mid: Dict[str, float] = store.get("prev_mid", {})
        ret_buf: Dict[str, List[float]] = store.get("ret_buf", {})
        n_trans: Dict[str, int] = store.get("n_trans", {})

        for product, od in state.order_depths.items():
            orders: List[Order] = []
            win = ROLLING_WINDOW.get(product, 50)
            mid = book_mid(od)
            spread = quoted_spread(od)
            if mid is None or spread is None:
                result[product] = orders
                continue

            min_move = max(MIN_ABSOLUTE, SPREAD_FRAC * spread)

            if product not in prev_mid:
                prev_mid[product] = mid
                ret_buf.setdefault(product, [])
                n_trans.setdefault(product, 0)
                result[product] = orders
                continue

            ret = mid - prev_mid[product]
            prev_mid[product] = mid
            buf = list(ret_buf.get(product, []))
            buf.append(ret)
            if len(buf) > win:
                buf = buf[-win:]
            ret_buf[product] = buf
            n_trans[product] = n_trans.get(product, 0) + 1

            pos = state.position.get(product, 0)
            room_long = POSITION_LIMIT - pos
            room_short = POSITION_LIMIT + pos

            if n_trans[product] <= win or len(buf) < win:
                result[product] = orders
                continue

            try:
                sig = statistics.stdev(buf)
            except statistics.StatisticsError:
                result[product] = orders
                continue

            if sig < 1e-6:
                result[product] = orders
                continue

            prev_r = buf[-1]
            z_thr = K_SIGMA * sig

            inv_skew = max(0, abs(pos) - 6) * 0.45
            clip = max(1, int(round(MAX_ORDER_SIZE - inv_skew)))

            allow_buy = pos < SOFT_CAP
            allow_sell = pos > -SOFT_CAP

            placed = False
            if pos >= HARD_UNWIND and od.buy_orders and room_short > 0:
                best_bid = max(od.buy_orders.keys())
                bid_vol = od.buy_orders[best_bid]
                if prev_r >= z_thr * 0.45 and abs(prev_r) >= min_move * 0.8:
                    qty = min(bid_vol, room_short, clip + 1)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))
                        placed = True
            elif pos <= -HARD_UNWIND and od.sell_orders and room_long > 0:
                best_ask = min(od.sell_orders.keys())
                ask_vol = -od.sell_orders[best_ask]
                if prev_r <= -z_thr * 0.45 and abs(prev_r) >= min_move * 0.8:
                    qty = min(ask_vol, room_long, clip + 1)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))
                        placed = True

            if not placed and od.sell_orders and room_long > 0 and allow_buy:
                best_ask = min(od.sell_orders.keys())
                ask_vol = -od.sell_orders[best_ask]
                if prev_r <= -z_thr and abs(prev_r) >= min_move:
                    qty = min(ask_vol, room_long, clip)
                    if qty > 0:
                        orders.append(Order(product, best_ask, qty))
            elif not placed and od.buy_orders and room_short > 0 and allow_sell:
                best_bid = max(od.buy_orders.keys())
                bid_vol = od.buy_orders[best_bid]
                if prev_r >= z_thr and abs(prev_r) >= min_move:
                    qty = min(bid_vol, room_short, clip)
                    if qty > 0:
                        orders.append(Order(product, best_bid, -qty))

            result[product] = orders

        store["prev_mid"] = prev_mid
        store["ret_buf"] = ret_buf
        store["n_trans"] = n_trans
        store["last_ts"] = state.timestamp
        conversions = 0
        trader_data = json.dumps(store)
        return result, conversions, trader_data

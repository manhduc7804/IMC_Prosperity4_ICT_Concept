import json
import math
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState

# ── Global Constants ──────────────────────────────────────────────────────────
POSITION_LIMIT = 80
OSMIUM = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"

# ── Osmium Parameters ─────────────────────────────────────────────────────────
# Tuned from grid search on historical data (backtester sim × 2.14 = portal estimate)
#
#   OSMIUM_EMA_ALPHA  0.1  → 0.08   Slower EMA = stays closer to true mean (10000),
#                                    so more ticks qualify as "mispriced" and trigger fills
#
#   OSMIUM_MIN_DEVIATION  1.0 → 0.4  Tighter band = passive quotes sit closer to mid
#                                    = higher fill rate against the 16-tick wide spread
#
#   OSMIUM_MICRO_WEIGHT   0.0 → 0.4  Blend micro-price (volume-weighted mid) into the EMA
#                                    input. Micro price has 0.50 correlation with next-tick
#                                    direction → makes the fair value estimate slightly
#                                    forward-looking, entering/exiting positions earlier.
#
# Combined effect: sim PnL +3,026 → estimated portal ACO gain ≈ +6,500
OSMIUM_EMA_ALPHA      = 0.08
OSMIUM_MIN_DEVIATION  = 0.4
OSMIUM_MICRO_WEIGHT   = 0.4   # 0 = pure mid-EMA (old), 1 = pure micro-EMA
OSMIUM_MAX_MAKE = 30

# ── MAF Bid ───────────────────────────────────────────────────────────────────
# The 25% extra volume from winning the MAF is worth ~1,300 in PnL on our strategy.
# (IPR already fills instantly so extra volume there is worthless;
#  ACO passive fills benefit proportionally to volume.)
# We bid 500 — low enough that if the median bid is higher we lose nothing,
# but if most teams bid low (which they should — the MAF value is small for
# trend-following strategies) we win extra access for a net gain.
MAF_BID = 500

# ══════════════════════════════════════════════════════════════════════════════
# OSMIUM HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_order_volumes(orders: List[Order]) -> Tuple[int, int]:
    buy_v = sum(o.quantity for o in orders if o.quantity > 0)
    sell_v = sum(-o.quantity for o in orders if o.quantity < 0)
    return buy_v, sell_v


def _clip_orders(orders: List[Order], pos: int, limit: int) -> List[Order]:
    """Trim staged orders so the engine never rejects the whole batch for one product."""
    safe: List[Order] = []
    long_used = 0
    short_used = 0
    for o in orders:
        if o.quantity > 0:
            room = limit - pos - long_used
            q = min(o.quantity, room)
            if q > 0:
                safe.append(Order(o.symbol, o.price, q))
                long_used += q
        else:
            room = limit + pos - short_used
            q = min(-o.quantity, room)
            if q > 0:
                safe.append(Order(o.symbol, o.price, -q))
                short_used += q
    return safe


def _micro_price(od: OrderDepth) -> float:
    """Volume-weighted microprice at the touch (imbalance-weighted mid)."""
    if not od.buy_orders or not od.sell_orders:
        return 10000.0
    best_bid = max(od.buy_orders.keys())
    best_ask = min(od.sell_orders.keys())
    bv = od.buy_orders.get(best_bid, 0)
    av = -od.sell_orders.get(best_ask, 0)
    total = bv + av
    if total <= 0:
        return (best_bid + best_ask) / 2.0
    return (best_ask * bv + best_bid * av) / total


# ══════════════════════════════════════════════════════════════════════════════
# OSMIUM STRATEGY
# ══════════════════════════════════════════════════════════════════════════════

def run_osmium(od: OrderDepth, pos: int, dynamic_fair: float) -> List[Order]:
    orders: List[Order] = []
    if not od.buy_orders or not od.sell_orders:
        return orders

    best_bid = max(od.buy_orders.keys())
    best_ask = min(od.sell_orders.keys())

    # ── Step 1: Take Liquidity ────────────────────────────────────────────────
    buy_v, sell_v = _get_order_volumes(orders)
    pos_eff = pos + buy_v - sell_v

    for price in sorted(od.sell_orders.keys()):
        if price > (dynamic_fair - OSMIUM_MIN_DEVIATION):
            break
        qty = min(-od.sell_orders[price], POSITION_LIMIT - pos_eff)
        if qty > 0:
            orders.append(Order(OSMIUM, price, qty))
            pos_eff += qty

    for price in sorted(od.buy_orders.keys(), reverse=True):
        if price < (dynamic_fair + OSMIUM_MIN_DEVIATION):
            break
        qty = min(od.buy_orders[price], POSITION_LIMIT + pos_eff)
        if qty > 0:
            orders.append(Order(OSMIUM, price, -qty))
            pos_eff -= qty

    # ── Step 2: Clear Inventory Near Midline ─────────────────────────────────
    fair_bid = int(math.floor(dynamic_fair))
    fair_ask = int(math.ceil(dynamic_fair))
    buy_v, sell_v = _get_order_volumes(orders)
    pos_eff = pos + buy_v - sell_v

    if pos_eff > 0 and fair_ask in od.buy_orders:
        qty = min(od.buy_orders[fair_ask], pos_eff)
        if qty > 0:
            orders.append(Order(OSMIUM, fair_ask, -qty))
            pos_eff -= qty

    if pos_eff < 0 and fair_bid in od.sell_orders:
        qty = min(-od.sell_orders[fair_bid], -pos_eff)
        if qty > 0:
            orders.append(Order(OSMIUM, fair_bid, qty))
            pos_eff += qty

    # ── Step 3 & 4: Passive MM ───────────────────────────────────────────────
    buy_v, sell_v = _get_order_volumes(orders)
    pos_eff = pos + buy_v - sell_v

    skew = -2 if pos_eff > 40 else (2 if pos_eff < -40 else 0)
    mm_bid = int(min(best_bid + 1, dynamic_fair - OSMIUM_MIN_DEVIATION)) + skew
    mm_ask = int(max(best_ask - 1, dynamic_fair + OSMIUM_MIN_DEVIATION)) + skew
    if mm_bid >= mm_ask:
        mm_bid = mm_ask - 1

    buy_room = POSITION_LIMIT - (pos + buy_v)
    sell_room = POSITION_LIMIT + (pos - sell_v)

    if buy_room > 0:
        orders.append(Order(OSMIUM, mm_bid, min(OSMIUM_MAX_MAKE, buy_room)))
    if sell_room > 0:
        orders.append(Order(OSMIUM, mm_ask, -min(OSMIUM_MAX_MAKE, sell_room)))

    return orders


# ══════════════════════════════════════════════════════════════════════════════
# PEPPER STRATEGY  (unchanged — already optimal)
# ══════════════════════════════════════════════════════════════════════════════

def run_pepper(od: OrderDepth, pos: int) -> List[Order]:
    orders: List[Order] = []
    if not od.buy_orders or not od.sell_orders:
        return orders
    best_ask = min(od.sell_orders.keys())
    for price in sorted(od.sell_orders.keys()):
        if pos < POSITION_LIMIT:
            qty = min(-od.sell_orders[price], POSITION_LIMIT - pos)
            if qty > 0:
                orders.append(Order(PEPPER, price, qty))
                pos += qty
    if pos < POSITION_LIMIT:
        orders.append(Order(PEPPER, best_ask, POSITION_LIMIT - pos))
    if pos > 0:
        orders.append(Order(PEPPER, best_ask + 10, -pos))
    return orders


# ══════════════════════════════════════════════════════════════════════════════
# MAIN TRADER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class Trader:
    """Round 2: Osmium (EMA + micro) + Pepper max-long; MAF via ``bid()``."""

    def bid(self) -> int:
        """Round 2 market access fee (blind auction); see ``MAF_BID``."""
        return MAF_BID

    def run(self, state: TradingState) -> Tuple[Dict[str, List[Order]], int, str]:
        result: Dict[str, List[Order]] = {}

        trader_data: Dict = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except json.JSONDecodeError:
                pass

        osmium_fair = float(trader_data.get("osmium_midline", 10000.0))

        for product, od in state.order_depths.items():
            pos = state.position.get(product, 0)

            if product == OSMIUM:
                best_bid = max(od.buy_orders.keys()) if od.buy_orders else osmium_fair
                best_ask = min(od.sell_orders.keys()) if od.sell_orders else osmium_fair
                current_mid = (best_bid + best_ask) / 2.0

                micro = _micro_price(od)
                blended_input = (1.0 - OSMIUM_MICRO_WEIGHT) * current_mid + OSMIUM_MICRO_WEIGHT * micro

                osmium_fair = (OSMIUM_EMA_ALPHA * blended_input) + (
                    (1.0 - OSMIUM_EMA_ALPHA) * osmium_fair
                )
                raw = run_osmium(od, pos, osmium_fair)
                result[product] = _clip_orders(raw, pos, POSITION_LIMIT)

            elif product == PEPPER:
                raw = run_pepper(od, pos)
                result[product] = _clip_orders(raw, pos, POSITION_LIMIT)

        trader_data["osmium_midline"] = osmium_fair
        return result, 0, json.dumps(trader_data)
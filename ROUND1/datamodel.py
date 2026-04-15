from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

Time = int
Symbol = str
Product = str
Position = int
UserId = str


class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: str) -> None:
        self.symbol = symbol
        self.product = product
        self.denomination = denomination


class OrderDepth:
    def __init__(
        self,
        buy_orders: Optional[Dict[int, int]] = None,
        sell_orders: Optional[Dict[int, int]] = None,
    ) -> None:
        self.buy_orders: Dict[int, int] = buy_orders if buy_orders is not None else {}
        self.sell_orders: Dict[int, int] = sell_orders if sell_orders is not None else {}


class Trade:
    def __init__(
        self,
        symbol: Symbol,
        price: int,
        quantity: int,
        buyer: UserId = "",
        seller: UserId = "",
        timestamp: int = 0,
    ) -> None:
        self.symbol = symbol
        self.price = int(price)
        self.quantity = int(quantity)
        self.buyer = buyer or ""
        self.seller = seller or ""
        self.timestamp = timestamp

    def __str__(self) -> str:
        return (
            f"({self.symbol}, {self.buyer} << {self.seller}, "
            f"{self.price}, {self.quantity}, {self.timestamp})"
        )


class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = int(price)
        self.quantity = int(quantity)

    def __str__(self) -> str:
        return f"({self.symbol}, {self.price}, {self.quantity})"

    def __repr__(self) -> str:
        return self.__str__()


class Observation:
    """Placeholder; round-specific fields can be added when needed."""

    def __init__(self, plainValueObservations: Optional[Dict[str, Any]] = None) -> None:
        self.plainValueObservations = plainValueObservations or {}


class TradingState:
    def __init__(
        self,
        traderData: str,
        timestamp: Time,
        listings: Dict[Symbol, Listing],
        order_depths: Dict[Symbol, OrderDepth],
        own_trades: Dict[Symbol, List[Trade]],
        market_trades: Dict[Symbol, List[Trade]],
        position: Dict[Product, Position],
        observations: Observation,
    ) -> None:
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)

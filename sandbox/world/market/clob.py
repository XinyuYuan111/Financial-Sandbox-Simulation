from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Literal

from sandbox.core.errors import ValidationError
from sandbox.core.ids import new_id
from sandbox.core.numeric import ceil_basis_points
from sandbox.world.ledger import Ledger


@dataclass(slots=True)
class Order:
    order_id: str
    agent_id: str
    side: Literal["buy", "sell"]
    order_type: Literal["limit", "protected_market"]
    price: int | None
    quantity: int
    remaining: int
    submitted_seq: int
    worst_price: int | None = None
    status: Literal["open", "partially_filled", "filled", "cancelled", "rejected"] = "open"
    locked_amount: int = 0


@dataclass(slots=True)
class Trade:
    trade_id: str
    buy_order_id: str
    sell_order_id: str
    buyer_id: str
    seller_id: str
    quantity: int
    price: int
    buyer_fee: int
    seller_fee: int


class CLOB:
    def __init__(self, orders: list[dict[str, object]] | None = None, trades: list[dict[str, object]] | None = None) -> None:
        self.orders: dict[str, Order] = {item["order_id"]: Order(**item) for item in orders or []}
        self.trades: list[Trade] = [Trade(**item) for item in trades or []]
        self.sequence = max((order.submitted_seq for order in self.orders.values()), default=0)

    def clone(self) -> "CLOB":
        return deepcopy(self)

    def _book(self, side: str) -> list[Order]:
        candidates = [order for order in self.orders.values() if order.side == side and order.status in {"open", "partially_filled"} and order.remaining > 0]
        if side == "sell":
            candidates.sort(key=lambda order: (order.price if order.price is not None else 2**63 - 1, order.submitted_seq, order.order_id))
        else:
            candidates.sort(key=lambda order: (-(order.price or 0), order.submitted_seq, order.order_id))
        return candidates

    def submit(
        self,
        *,
        agent_id: str,
        side: Literal["buy", "sell"],
        quantity: int,
        order_type: Literal["limit", "protected_market"],
        price: int | None,
        worst_price: int | None,
        ledger: Ledger,
        maker_fee_bps: int,
        taker_fee_bps: int,
        base_asset: str = "TOKEN",
        quote_asset: str = "USDX",
        fee_account: str = "fee_account",
    ) -> tuple[Order, list[Trade]]:
        if quantity <= 0:
            raise ValidationError("order quantity must be positive")
        if order_type == "limit" and (price is None or price <= 0):
            raise ValidationError("limit orders require a positive price")
        if order_type == "protected_market" and (worst_price is None or worst_price <= 0):
            raise ValidationError("protected market orders require worst_price")
        self.sequence += 1
        order = Order(new_id("ord"), agent_id, side, order_type, price, quantity, quantity, self.sequence, worst_price)
        if side == "sell":
            ledger.lock(agent_id, base_asset, quantity)
            order.locked_amount = quantity
        else:
            reserve_price = price if price is not None else worst_price
            assert reserve_price is not None
            reserve = reserve_price * quantity + ceil_basis_points(reserve_price * quantity, taker_fee_bps)
            ledger.lock(agent_id, quote_asset, reserve)
            order.locked_amount = reserve
        self.orders[order.order_id] = order
        trades: list[Trade] = []
        opposite = "sell" if side == "buy" else "buy"
        for maker in self._book(opposite):
            if order.remaining <= 0:
                break
            if maker.agent_id == agent_id:
                continue
            if maker.price is None:
                continue
            if order.order_type == "limit":
                if side == "buy" and maker.price > (price or 0):
                    break
                if side == "sell" and maker.price < (price or 0):
                    break
            if order.worst_price is not None:
                if side == "buy" and maker.price > order.worst_price:
                    break
                if side == "sell" and maker.price < order.worst_price:
                    break
            quantity_fill = min(order.remaining, maker.remaining)
            trade = self._settle(
                incoming=order,
                maker=maker,
                quantity=quantity_fill,
                price=maker.price,
                ledger=ledger,
                maker_fee_bps=maker_fee_bps,
                taker_fee_bps=taker_fee_bps,
                base_asset=base_asset,
                quote_asset=quote_asset,
                fee_account=fee_account,
            )
            self._rebalance_lock(maker, ledger, base_asset, quote_asset, maker_fee_bps)
            trades.append(trade)
        if order.remaining == 0:
            order.status = "filled"
        elif trades:
            order.status = "partially_filled"
        if order.order_type == "protected_market" and order.remaining:
            self._release_lock(order, ledger, base_asset, quote_asset, taker_fee_bps)
            order.status = "cancelled"
        else:
            self._rebalance_lock(order, ledger, base_asset, quote_asset, maker_fee_bps)
        return order, trades

    def _settle(self, *, incoming: Order, maker: Order, quantity: int, price: int, ledger: Ledger, maker_fee_bps: int, taker_fee_bps: int, base_asset: str, quote_asset: str, fee_account: str) -> Trade:
        buyer = incoming.agent_id if incoming.side == "buy" else maker.agent_id
        seller = incoming.agent_id if incoming.side == "sell" else maker.agent_id
        fees = ledger.settle_trade(
            buyer=buyer,
            seller=seller,
            quantity=quantity,
            price=price,
            buyer_fee_bps=taker_fee_bps if incoming.side == "buy" else maker_fee_bps,
            seller_fee_bps=taker_fee_bps if incoming.side == "sell" else maker_fee_bps,
            base_asset=base_asset,
            quote_asset=quote_asset,
            fee_account=fee_account,
        )
        incoming.remaining -= quantity
        maker.remaining -= quantity
        buy_order = incoming if incoming.side == "buy" else maker
        sell_order = incoming if incoming.side == "sell" else maker
        buy_order.locked_amount -= quantity * price + fees["buyer_fee"]
        sell_order.locked_amount -= quantity
        maker.status = "filled" if maker.remaining == 0 else "partially_filled"
        trade = Trade(new_id("trd"), incoming.order_id if incoming.side == "buy" else maker.order_id, incoming.order_id if incoming.side == "sell" else maker.order_id, buyer, seller, quantity, price, fees["buyer_fee"], fees["seller_fee"])
        self.trades.append(trade)
        return trade

    def _release_lock(self, order: Order, ledger: Ledger, base_asset: str, quote_asset: str, taker_fee_bps: int) -> None:
        if order.locked_amount:
            ledger.unlock(order.agent_id, base_asset if order.side == "sell" else quote_asset, order.locked_amount)
            order.locked_amount = 0

    def _rebalance_lock(self, order: Order, ledger: Ledger, base_asset: str, quote_asset: str, taker_fee_bps: int) -> None:
        asset = base_asset if order.side == "sell" else quote_asset
        if order.side == "sell":
            required = order.remaining
        else:
            required = (order.price or order.worst_price or 0) * order.remaining
            required += ceil_basis_points(required, taker_fee_bps)
        if order.locked_amount > required:
            release = order.locked_amount - required
            ledger.unlock(order.agent_id, asset, release)
            order.locked_amount = required

    def cancel(self, order_id: str, agent_id: str, ledger: Ledger, *, base_asset: str = "TOKEN", quote_asset: str = "USDX") -> Order:
        order = self.orders.get(order_id)
        if order is None or order.agent_id != agent_id:
            raise ValidationError("order is not owned by agent")
        if order.status not in {"open", "partially_filled"}:
            raise ValidationError("order cannot be cancelled")
        asset = base_asset if order.side == "sell" else quote_asset
        if order.locked_amount:
            ledger.unlock(agent_id, asset, order.locked_amount)
            order.locked_amount = 0
        order.status = "cancelled"
        return order

    def to_json(self) -> dict[str, object]:
        return {"orders": [asdict(order) for order in self.orders.values()], "trades": [asdict(trade) for trade in self.trades], "sequence": self.sequence}

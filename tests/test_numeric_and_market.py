from __future__ import annotations

import unittest

from pydantic import ValidationError as PydanticValidationError

from sandbox.contracts.scenario import MarketConfig
from sandbox.core.errors import ValidationError
from sandbox.world.ledger import Ledger
from sandbox.world.market.clob import CLOB


class NumericAndMarketTests(unittest.TestCase):
    def test_market_contract_rejects_float_price_tick(self) -> None:
        with self.assertRaises(PydanticValidationError):
            MarketConfig(price_tick=1.0)

    def test_ledger_rejects_float_amount(self) -> None:
        ledger = Ledger()
        with self.assertRaises(ValidationError):
            ledger.credit("agent", "TOKEN", 1.5, reason="invalid")  # type: ignore[arg-type]

    def test_price_time_priority_and_asset_conservation(self) -> None:
        ledger = Ledger()
        for seller in ("seller_a", "seller_b"):
            ledger.credit(seller, "TOKEN", 100, reason="mint")
            ledger.credit(seller, "USDX", 0, reason="mint")
        ledger.credit("buyer", "TOKEN", 0, reason="mint")
        ledger.credit("buyer", "USDX", 50_000, reason="mint")
        ledger.credit("fee_account", "TOKEN", 0, reason="open")
        ledger.credit("fee_account", "USDX", 0, reason="open")
        token_before = ledger.total("TOKEN")
        quote_before = ledger.total("USDX")
        book = CLOB()
        first, _ = book.submit(agent_id="seller_a", side="sell", quantity=50, order_type="limit", price=100, worst_price=None, ledger=ledger, maker_fee_bps=5, taker_fee_bps=10)
        second, _ = book.submit(agent_id="seller_b", side="sell", quantity=50, order_type="limit", price=100, worst_price=None, ledger=ledger, maker_fee_bps=5, taker_fee_bps=10)
        _, trades = book.submit(agent_id="buyer", side="buy", quantity=60, order_type="limit", price=100, worst_price=None, ledger=ledger, maker_fee_bps=5, taker_fee_bps=10)
        self.assertEqual([trade.sell_order_id for trade in trades], [first.order_id, second.order_id])
        self.assertEqual([trade.quantity for trade in trades], [50, 10])
        self.assertEqual(ledger.total("TOKEN"), token_before)
        self.assertEqual(ledger.total("USDX"), quote_before)
        self.assertEqual(ledger.balance("fee_account", "USDX"), 10)


if __name__ == "__main__":
    unittest.main()


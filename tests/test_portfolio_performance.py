from __future__ import annotations

import unittest

from sandbox.control.run_manager import RunManager


class PortfolioPerformanceTests(unittest.TestCase):
    baseline = {
        "base_asset": "TOKEN",
        "quote_asset": "USDX",
        "initial_base_amount": 5,
        "initial_quote_amount": 100,
        "initial_mid_price": 100,
    }

    @staticmethod
    def portfolio(*, token_free: int, token_locked: int, usdx_free: int, usdx_locked: int) -> dict[str, object]:
        return {
            "balances": {
                "TOKEN": {"free": token_free, "locked": token_locked},
                "USDX": {"free": usdx_free, "locked": usdx_locked},
            },
            "open_orders": [],
        }

    def value(self, portfolio: dict[str, object], market: dict[str, object]) -> dict[str, object]:
        return RunManager._portfolio_performance(
            portfolio,
            market,
            self.baseline,
            sim_time_us=12_000_000,
        )

    def test_midpoint_valuation_counts_free_and_locked_balances(self) -> None:
        performance = self.value(
            self.portfolio(token_free=2, token_locked=3, usdx_free=60, usdx_locked=40),
            {
                "bids": [{"price": 99}],
                "asks": [{"price": 102}],
                "last_trade": {"price": 97},
            },
        )

        self.assertEqual(performance["valuation_price_source"], "midpoint")
        self.assertEqual(performance["valuation_price_milli"], 100_500)
        self.assertEqual(performance["initial_value_milli_quote"], "600000")
        self.assertEqual(performance["current_value_milli_quote"], "602500")
        self.assertEqual(performance["change_value_milli_quote"], "2500")
        self.assertEqual(performance["return_bps"], 41)
        all_free = self.value(
            self.portfolio(token_free=5, token_locked=0, usdx_free=100, usdx_locked=0),
            {"bids": [{"price": 99}], "asks": [{"price": 102}], "last_trade": None},
        )
        self.assertEqual(performance["current_value_milli_quote"], all_free["current_value_milli_quote"])
        self.assertEqual(performance["return_bps"], all_free["return_bps"])

    def test_price_fallbacks_prefer_trade_then_one_sided_quote_then_initial_price(self) -> None:
        portfolio = self.portfolio(token_free=5, token_locked=0, usdx_free=100, usdx_locked=0)
        cases = [
            (
                {"bids": [{"price": 101}], "asks": [{"price": 100}], "last_trade": {"price": 98}},
                "last_trade",
                98_000,
            ),
            ({"bids": [{"price": 97}], "asks": [], "last_trade": None}, "best_bid_only", 97_000),
            ({"bids": [], "asks": [{"price": 103}], "last_trade": None}, "best_ask_only", 103_000),
            ({"bids": [{"price": 101}], "asks": [{"price": 100}], "last_trade": None}, "initial_price", 100_000),
            ({"bids": [], "asks": [], "last_trade": None}, "initial_price", 100_000),
        ]

        for market, source, price_milli in cases:
            with self.subTest(source=source):
                performance = self.value(portfolio, market)
                self.assertEqual(performance["valuation_price_source"], source)
                self.assertEqual(performance["valuation_price_milli"], price_milli)

    def test_negative_return_rounds_toward_zero(self) -> None:
        performance = self.value(
            self.portfolio(token_free=5, token_locked=0, usdx_free=100, usdx_locked=0),
            {"bids": [{"price": 98}], "asks": [{"price": 100}], "last_trade": None},
        )

        self.assertEqual(performance["current_value_milli_quote"], "595000")
        self.assertEqual(performance["return_bps"], -83)

    def test_zero_initial_value_has_no_return_rate(self) -> None:
        performance = RunManager._portfolio_performance(
            self.portfolio(token_free=0, token_locked=0, usdx_free=0, usdx_locked=0),
            {"bids": [], "asks": [], "last_trade": None},
            {**self.baseline, "initial_base_amount": 0, "initial_quote_amount": 0},
            sim_time_us=0,
        )

        self.assertIsNone(performance["return_bps"])


if __name__ == "__main__":
    unittest.main()

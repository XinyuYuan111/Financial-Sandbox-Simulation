from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from sandbox.core.errors import ValidationError
from sandbox.core.numeric import ceil_basis_points, require_int


@dataclass(slots=True)
class Account:
    free: int = 0
    locked: int = 0


class Ledger:
    def __init__(self, balances: dict[str, dict[str, dict[str, int]]] | None = None) -> None:
        self.balances: dict[str, dict[str, Account]] = {}
        for owner, assets in (balances or {}).items():
            self.balances[owner] = {asset: Account(**values) for asset, values in assets.items()}
        self.postings: list[dict[str, object]] = []

    def clone(self) -> "Ledger":
        copy = Ledger()
        copy.balances = deepcopy(self.balances)
        copy.postings = deepcopy(self.postings)
        return copy

    def _account(self, owner: str, asset: str) -> Account:
        return self.balances.setdefault(owner, {}).setdefault(asset, Account())

    def balance(self, owner: str, asset: str) -> int:
        return self._account(owner, asset).free

    def has_owner(self, owner: str) -> bool:
        return owner in self.balances

    def has_account(self, owner: str, asset: str) -> bool:
        return owner in self.balances and asset in self.balances[owner]

    def open_account(self, owner: str, assets: list[str], *, reason: str) -> None:
        if owner in self.balances:
            raise ValidationError(f"ledger owner '{owner}' already exists")
        self.balances[owner] = {}
        for asset in assets:
            self.balances[owner][asset] = Account()
            self.postings.append({"owner": owner, "asset": asset, "amount": 0, "reason": reason, "kind": "open"})

    def total(self, asset: str) -> int:
        return sum(account.free + account.locked for assets in self.balances.values() for name, account in assets.items() if name == asset)

    def credit(self, owner: str, asset: str, amount: int, *, reason: str) -> None:
        require_int(amount, "amount")
        self._account(owner, asset).free += amount
        self.postings.append({"owner": owner, "asset": asset, "amount": amount, "reason": reason, "kind": "credit"})

    def debit(self, owner: str, asset: str, amount: int, *, reason: str) -> None:
        require_int(amount, "amount")
        account = self._account(owner, asset)
        if account.free < amount:
            raise ValidationError(f"insufficient {asset} balance for {owner}")
        account.free -= amount
        self.postings.append({"owner": owner, "asset": asset, "amount": -amount, "reason": reason, "kind": "debit"})

    def lock(self, owner: str, asset: str, amount: int) -> None:
        require_int(amount, "amount")
        account = self._account(owner, asset)
        if account.free < amount:
            raise ValidationError(f"insufficient free {asset} balance for order")
        account.free -= amount
        account.locked += amount
        self.postings.append({"owner": owner, "asset": asset, "amount": amount, "reason": "order_lock", "kind": "lock"})

    def unlock(self, owner: str, asset: str, amount: int) -> None:
        require_int(amount, "amount")
        account = self._account(owner, asset)
        if account.locked < amount:
            raise ValidationError("cannot unlock more than the order lock")
        account.locked -= amount
        account.free += amount
        self.postings.append({"owner": owner, "asset": asset, "amount": amount, "reason": "order_unlock", "kind": "unlock"})

    def transfer_locked(self, seller: str, buyer: str, asset: str, amount: int) -> None:
        require_int(amount, "amount")
        account = self._account(seller, asset)
        if account.locked < amount:
            raise ValidationError("seller order lock is insufficient")
        account.locked -= amount
        self._account(buyer, asset).free += amount
        self.postings.append({"owner": seller, "asset": asset, "amount": -amount, "reason": "trade_delivery", "kind": "locked_transfer"})
        self.postings.append({"owner": buyer, "asset": asset, "amount": amount, "reason": "trade_delivery", "kind": "credit"})

    def transfer_free(self, seller: str, buyer: str, asset: str, amount: int, *, reason: str = "trade_payment") -> None:
        self.debit(seller, asset, amount, reason=reason)
        self.credit(buyer, asset, amount, reason=reason)

    def settle_trade(
        self,
        *,
        buyer: str,
        seller: str,
        quantity: int,
        price: int,
        buyer_fee_bps: int,
        seller_fee_bps: int,
        base_asset: str = "TOKEN",
        quote_asset: str = "USDX",
        fee_account: str = "fee_account",
    ) -> dict[str, int]:
        require_int(quantity, "quantity")
        require_int(price, "price")
        gross = quantity * price
        buyer_fee = ceil_basis_points(gross, buyer_fee_bps)
        seller_fee = ceil_basis_points(gross, seller_fee_bps)
        self.transfer_locked(seller, buyer, base_asset, quantity)
        self.transfer_locked(buyer, seller, quote_asset, gross)
        if buyer_fee:
            self.transfer_locked(buyer, fee_account, quote_asset, buyer_fee)
        if seller_fee:
            self.debit(seller, quote_asset, seller_fee, reason="seller_fee")
            self.credit(fee_account, quote_asset, seller_fee, reason="seller_fee")
        return {"gross": gross, "buyer_fee": buyer_fee, "seller_fee": seller_fee}

    def to_json(self) -> dict[str, object]:
        return {
            "balances": {owner: {asset: {"free": account.free, "locked": account.locked} for asset, account in assets.items()} for owner, assets in self.balances.items()},
            "postings": self.postings,
        }

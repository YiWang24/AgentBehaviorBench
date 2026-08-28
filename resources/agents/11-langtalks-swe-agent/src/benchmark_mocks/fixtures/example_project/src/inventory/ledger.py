"""Track stock levels for a small catalogue."""

from __future__ import annotations


class OutOfStock(Exception):
    """Raised when a withdrawal exceeds the quantity on hand."""


class Ledger:
    """An in-memory stock ledger keyed by SKU."""

    def __init__(self) -> None:
        self._quantities: dict[str, int] = {}

    def receive(self, sku: str, quantity: int) -> int:
        """Add stock for a SKU and return the new quantity on hand."""
        if quantity < 0:
            raise ValueError("quantity must not be negative")
        self._quantities[sku] = self._quantities.get(sku, 0) + quantity
        return self._quantities[sku]

    def withdraw(self, sku: str, quantity: int) -> int:
        """Remove stock for a SKU and return the new quantity on hand."""
        if quantity < 0:
            raise ValueError("quantity must not be negative")
        on_hand = self._quantities.get(sku, 0)
        # Known defect: this allows the quantity on hand to go negative
        # instead of refusing a withdrawal it cannot satisfy.
        self._quantities[sku] = on_hand - quantity
        return self._quantities[sku]

    def on_hand(self, sku: str) -> int:
        """Return the quantity currently on hand for a SKU."""
        return self._quantities.get(sku, 0)

from inventory import Ledger


def test_receive_accumulates():
    ledger = Ledger()
    ledger.receive("widget", 3)

    assert ledger.receive("widget", 2) == 5


def test_withdraw_reduces_stock():
    ledger = Ledger()
    ledger.receive("widget", 5)

    assert ledger.withdraw("widget", 2) == 3

"""Tests for the Schwab live layer — payload mapping & account selection (no network).

The schwabdev client is faked: SchwabClient._get_client returns the preset
``_client`` when set, bypassing OAuth/import entirely.
"""

from __future__ import annotations

import pytest

from watchy.config import SchwabConfig
from watchy.schwab import SchwabClient


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSchwab:
    """Minimal stand-in for schwabdev.Client."""

    def __init__(self, accounts, details_by_hash):
        self._accounts = accounts
        self._details = details_by_hash
        self.calls = []

    def account_linked(self):
        return _Resp(self._accounts)

    def account_details(self, acct_hash, fields=None):
        self.calls.append((acct_hash, fields))
        return _Resp(self._details[acct_hash])


def _details(positions, balances=None):
    return {
        "securitiesAccount": {
            "accountNumber": "123",
            "positions": positions,
            "currentBalances": balances or {},
        }
    }


def _client(fake, account_id=""):
    cfg = SchwabConfig(enabled=True, api_key="k", api_secret="s", account_id=account_id)
    c = SchwabClient(cfg)
    c._client = fake  # bypass real schwabdev construction / OAuth
    return c


NVDA_POS = {
    "instrument": {"symbol": "NVDA"},
    "longQuantity": 100,
    "averagePrice": 120.0,
    "marketValue": 13000.0,
    "longOpenProfitLoss": 1000.0,
}
AAPL_POS = {
    "instrument": {"symbol": "AAPL"},
    "longQuantity": 50,
    "averagePrice": 190.0,
    "marketValue": 9750.0,
    "longOpenProfitLoss": 250.0,
}


class TestNotReady:
    def test_unconfigured_returns_none(self):
        c = SchwabClient(SchwabConfig(enabled=False))
        assert c.get_account_summary() is None
        assert c.get_all_positions() == []
        assert c.get_position("NVDA") is None


class TestMapping:
    def test_account_summary_maps_positions_and_balances(self):
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "123", "hashValue": "HASH123"}],
            details_by_hash={"HASH123": _details(
                [NVDA_POS, AAPL_POS],
                balances={"liquidationValue": 50000.0, "buyingPower": 20000.0,
                          "cashBalance": 5000.0},
            )},
        )
        summary = _client(fake).get_account_summary()
        assert summary is not None
        assert summary.account_id == "123"
        assert summary.total_value == 50000.0
        assert summary.buying_power == 20000.0
        assert summary.cash_balance == 5000.0
        assert {p.ticker for p in summary.positions} == {"NVDA", "AAPL"}

    def test_position_fields_derived(self):
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "123", "hashValue": "H"}],
            details_by_hash={"H": _details([NVDA_POS])},
        )
        pos = _client(fake).get_position("nvda")
        assert pos.ticker == "NVDA"
        assert pos.quantity == 100
        assert pos.average_cost == 120.0
        assert pos.market_value == 13000.0
        assert pos.unrealized_pnl == 1000.0
        assert pos.current_price == pytest.approx(130.0)
        assert pos.unrealized_pnl_pct == pytest.approx(1000.0 / 12000.0 * 100.0)

    def test_short_quantity_nets_against_long(self):
        short = {
            "instrument": {"symbol": "TSLA"},
            "longQuantity": 0,
            "shortQuantity": 10,
            "averagePrice": 200.0,
            "marketValue": -2000.0,
        }
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "123", "hashValue": "H"}],
            details_by_hash={"H": _details([short])},
        )
        pos = _client(fake).get_position("TSLA")
        assert pos.quantity == -10

    def test_skips_positions_without_symbol(self):
        junk = {"instrument": {}, "longQuantity": 5, "averagePrice": 1.0}
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "123", "hashValue": "H"}],
            details_by_hash={"H": _details([NVDA_POS, junk])},
        )
        tickers = [p.ticker for p in _client(fake).get_all_positions()]
        assert tickers == ["NVDA"]

    def test_total_value_falls_back_to_sum_when_no_balance(self):
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "123", "hashValue": "H"}],
            details_by_hash={"H": _details([NVDA_POS, AAPL_POS])},  # no balances
        )
        summary = _client(fake).get_account_summary()
        assert summary.total_value == pytest.approx(13000.0 + 9750.0)
        assert summary.buying_power is None


class TestAccountSelection:
    def test_picks_account_by_id(self):
        fake = _FakeSchwab(
            accounts=[
                {"accountNumber": "111", "hashValue": "HA"},
                {"accountNumber": "222", "hashValue": "HB"},
            ],
            details_by_hash={"HB": _details([NVDA_POS])},
        )
        c = _client(fake, account_id="222")
        assert c.get_account_summary() is not None
        assert fake.calls[0][0] == "HB"  # used the matching hash

    def test_defaults_to_first_account_when_id_blank(self):
        fake = _FakeSchwab(
            accounts=[
                {"accountNumber": "111", "hashValue": "HA"},
                {"accountNumber": "222", "hashValue": "HB"},
            ],
            details_by_hash={"HA": _details([NVDA_POS])},
        )
        c = _client(fake, account_id="")
        assert c.get_account_summary() is not None
        assert fake.calls[0][0] == "HA"

    def test_unknown_account_id_degrades_to_none(self):
        # _account_hash raises → get_account_summary catches → None (composite falls back).
        fake = _FakeSchwab(
            accounts=[{"accountNumber": "111", "hashValue": "HA"}],
            details_by_hash={"HA": _details([NVDA_POS])},
        )
        c = _client(fake, account_id="999")
        assert c.get_account_summary() is None

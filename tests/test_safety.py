"""Offline tests for the anti-hallucination safety layer (no network)."""

import json
import time

import pytest

from mcp_pionex import safety
from mcp_pionex.safety import SafetyError


def test_validate_enum_rejects_and_lists_valid_values():
    with pytest.raises(SafetyError) as exc:
        safety.validate_enum("2H", safety.VALID_KLINE_INTERVALS, "interval")
    assert "1D" in str(exc.value)
    assert "Do not invent" in str(exc.value)


def test_validate_enum_accepts_exact_value():
    assert safety.validate_enum("BUY", safety.VALID_SIDES, "side") == "BUY"


def test_notional_cap_blocks_over_limit():
    cap = safety.SETTINGS.max_order_notional
    with pytest.raises(SafetyError) as exc:
        safety.check_notional_cap(cap + 1, "test")
    assert "PIONEX_MCP_MAX_ORDER_NOTIONAL" in str(exc.value)
    safety.check_notional_cap(cap, "test")  # at the cap is allowed


def test_notional_cap_blocks_non_positive():
    with pytest.raises(SafetyError):
        safety.check_notional_cap(0, "test")


def test_two_phase_token_roundtrip_and_single_use():
    prepared = safety.prepare_action("place_order", {"symbol": "BTC_USDT"}, "test")
    token = prepared["confirmation_token"]
    entry = safety.take_pending(token)
    assert entry["params"] == {"symbol": "BTC_USDT"}
    with pytest.raises(SafetyError):  # single use
        safety.take_pending(token)


def test_two_phase_token_unknown():
    with pytest.raises(SafetyError):
        safety.take_pending("not-a-real-token")


def test_two_phase_token_is_parameter_bound():
    a = safety.prepare_action("place_order", {"symbol": "BTC_USDT"}, "s")
    b = safety.prepare_action("place_order", {"symbol": "ETH_USDT"}, "s")
    # fingerprint prefix differs when params differ
    assert a["confirmation_token"].split("-")[0] != b["confirmation_token"].split("-")[0]


def test_two_phase_token_expires(monkeypatch):
    prepared = safety.prepare_action("place_order", {"x": 1}, "s")
    token = prepared["confirmation_token"]
    entry = safety._PENDING[token]
    entry["expires_at"] = time.monotonic() - 1
    with pytest.raises(SafetyError) as exc:
        safety.take_pending(token)
    assert "expired" in str(exc.value)


def test_envelope_has_provenance():
    body = json.loads(safety.envelope("GET /x", {"a": 1}, computed=True, note="n"))
    assert body["ok"] is True
    assert body["source"] == "GET /x"
    assert body["computed"] is True
    assert body["data"] == {"a": 1}
    assert "fetched_at" in body


def test_error_envelope_is_verbatim():
    class FakeApiError(Exception):
        code = "INVALID_APIKEY"
        message = "Invalid apikey"

    body = json.loads(safety.error_envelope(FakeApiError()))
    assert body["ok"] is False
    assert body["error_code"] == "INVALID_APIKEY"
    assert body["error_message"] == "Invalid apikey"


def test_gates_blocked_by_default():
    for gate in (safety.require_trading, safety.require_bots, safety.require_earn):
        with pytest.raises(SafetyError):
            gate()

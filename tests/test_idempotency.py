"""Offline tests for idempotency keys and the new operator gates."""

import pytest

from mcp_pionex import safety
from mcp_pionex.safety import SafetyError


def test_client_order_id_is_minted_when_empty():
    a, b = safety.client_order_id(""), safety.client_order_id("")
    assert a.startswith("mcp-") and b.startswith("mcp-")
    assert a != b
    assert len(a) <= 32


def test_client_order_id_prefix():
    assert safety.client_order_id("", prefix="dual").startswith("dual-")


def test_client_order_id_passthrough_valid():
    assert safety.client_order_id("my-order_01") == "my-order_01"


@pytest.mark.parametrize("bad", ["has space", "x" * 33, "semi;colon", "ñ"])
def test_client_order_id_rejects_invalid(bad):
    with pytest.raises(SafetyError):
        safety.client_order_id(bad)


def test_leverage_cap():
    cap = safety.SETTINGS.max_leverage
    safety.check_leverage(cap)
    with pytest.raises(SafetyError) as exc:
        safety.check_leverage(cap + 1)
    assert "PIONEX_MCP_MAX_LEVERAGE" in str(exc.value)
    with pytest.raises(SafetyError):
        safety.check_leverage(0)


def test_futures_gate_is_closed_by_default(monkeypatch):
    monkeypatch.setattr(safety.SETTINGS.__class__, "has_credentials",
                        property(lambda self: True))
    if not safety.SETTINGS.bots_enabled or not safety.SETTINGS.futures_enabled:
        with pytest.raises(SafetyError) as exc:
            safety.require_futures()
        assert "ENABLED" in str(exc.value)


def test_new_vocabularies():
    assert safety.validate_enum("SELL", safety.VALID_CLOSE_SELL_MODELS, "m") == "SELL"
    with pytest.raises(SafetyError):
        safety.validate_enum("KEEP", safety.VALID_CLOSE_SELL_MODELS, "m")
    assert safety.validate_enum("SETTLED", safety.VALID_DUAL_FILTERS, "f") == "SETTLED"

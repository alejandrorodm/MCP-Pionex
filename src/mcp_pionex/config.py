"""
Configuration for the Pionex MCP server.

Everything is driven by environment variables so the safety posture is
decided by the *operator*, never by the model. Defaults are maximally
conservative: no credentials, read-only, tight limits.
"""

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _env_list(name: str) -> list:
    raw = os.environ.get(name, "")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    # -- credentials -------------------------------------------------------
    api_key: str = field(default_factory=lambda: os.environ.get("PIONEX_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.environ.get("PIONEX_API_SECRET", ""))

    # -- capability gates (all OFF by default) -----------------------------
    # Trading, bots and earn writes must be explicitly enabled by a human.
    trading_enabled: bool = field(default_factory=lambda: _env_bool("PIONEX_MCP_TRADING_ENABLED"))
    bots_enabled: bool = field(default_factory=lambda: _env_bool("PIONEX_MCP_BOTS_ENABLED"))
    earn_enabled: bool = field(default_factory=lambda: _env_bool("PIONEX_MCP_EARN_ENABLED"))

    # -- hard limits -------------------------------------------------------
    # Max quote-notional (in the pair's quote currency, typically USDT) that
    # a single order / bot investment prepared through this server may have.
    max_order_notional: float = field(
        default_factory=lambda: _env_float("PIONEX_MCP_MAX_ORDER_NOTIONAL", 100.0)
    )
    # A LIMIT price further than this % away from the live mid-price is
    # rejected (fat-finger / hallucinated-price guard).
    max_price_deviation_pct: float = field(
        default_factory=lambda: _env_float("PIONEX_MCP_MAX_PRICE_DEVIATION_PCT", 10.0)
    )
    # Optional symbol whitelist ("BTC_USDT,ETH_USDT"). Empty = all symbols
    # that exist on the exchange are allowed (existence is always verified).
    symbol_whitelist: list = field(default_factory=lambda: _env_list("PIONEX_MCP_SYMBOL_WHITELIST"))

    # -- two-phase confirmation -------------------------------------------
    # Seconds a prepared action's confirmation token stays valid.
    confirmation_ttl: float = field(
        default_factory=lambda: _env_float("PIONEX_MCP_CONFIRMATION_TTL", 120.0)
    )

    # -- audit -------------------------------------------------------------
    audit_log: str = field(
        default_factory=lambda: os.environ.get(
            "PIONEX_MCP_AUDIT_LOG",
            os.path.expanduser("~/.mcp_pionex/audit.jsonl"),
        )
    )

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)


SETTINGS = Settings()

"""
Pionex MCP server entry point.

Registers every tool group on a FastMCP instance and serves over stdio.
"""

from mcp.server.mcpserver import MCPServer

from mcp_pionex import __version__
from mcp_pionex.config import SETTINGS
from mcp_pionex import safety

INSTRUCTIONS = """
Pionex exchange MCP server (spot trading, market data, grid bots, dual investment).

STRICT ANTI-HALLUCINATION RULES — you MUST follow these:
1. NEVER state a price, balance, order status or any market fact without calling a
   tool first in this conversation turn. Your training data about crypto prices is
   always stale.
2. Only report values that literally appear inside the `data` field of a tool
   response. If a field is missing, say it is not available — do not fill gaps.
3. Symbols use the exchange's exact format `BASE_QUOTE` (e.g. `BTC_USDT`). If
   unsure a symbol exists, call list_symbols or get_symbol_info first.
4. All state-changing actions (orders, bots, investments) are two-phase:
   `prepare_*` validates and returns a confirmation token; execution happens only
   via `confirm_action` with that exact token, after the human user explicitly
   approves the shown summary. Never fabricate, reuse or guess tokens.
5. Operator-set limits (read-only mode, notional caps, price-deviation caps,
   symbol whitelist) are enforced server-side and CANNOT be changed from the
   conversation. If a guardrail blocks an action, tell the user which environment
   variable controls it.
6. Report API errors verbatim (code + message). Do not invent explanations.
"""

mcp = MCPServer("pionex", instructions=INSTRUCTIONS.strip())


# ---------------------------------------------------------------------------
# Meta / introspection tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_server_status() -> str:
    """Server status: version, which capability gates (trading/bots/earn) are
    enabled, active limits, and whether API credentials are configured.
    Call this first when a session starts or when a tool reports it is disabled."""
    return safety.envelope("mcp-pionex internal", {
        "version": __version__,
        "credentials_configured": SETTINGS.has_credentials,
        "trading_enabled": SETTINGS.trading_enabled,
        "bots_enabled": SETTINGS.bots_enabled,
        "earn_enabled": SETTINGS.earn_enabled,
        "max_order_notional": SETTINGS.max_order_notional,
        "max_price_deviation_pct": SETTINGS.max_price_deviation_pct,
        "symbol_whitelist": SETTINGS.symbol_whitelist or "all exchange symbols allowed",
        "confirmation_ttl_seconds": SETTINGS.confirmation_ttl,
        "pending_confirmations": safety.pending_count(),
        "audit_log": SETTINGS.audit_log,
    })


@mcp.tool()
def get_safety_rules() -> str:
    """The full list of anti-hallucination and safety rules this server
    enforces. Use it to explain to the user why an action was blocked."""
    return safety.envelope("mcp-pionex internal", {
        "rules": [
            "Closed vocabularies: side, order type, interval, market type, grid type "
            "and dual-investment type are validated against hardcoded whitelists.",
            "Live symbol verification: every symbol is checked against the exchange's "
            "current symbol list (10-min cache) before any request that uses it.",
            "Two-phase commit: state-changing actions require prepare_* followed by "
            "confirm_action with a single-use, parameter-bound, expiring token.",
            "Notional cap per action: PIONEX_MCP_MAX_ORDER_NOTIONAL "
            f"(currently {SETTINGS.max_order_notional}).",
            "LIMIT price deviation guard: PIONEX_MCP_MAX_PRICE_DEVIATION_PCT "
            f"(currently {SETTINGS.max_price_deviation_pct}%) vs live mid-price.",
            "Capability gates: trading / bots / earn writes are off unless the operator "
            "sets PIONEX_MCP_TRADING_ENABLED / _BOTS_ENABLED / _EARN_ENABLED.",
            "Optional symbol whitelist: PIONEX_MCP_SYMBOL_WHITELIST.",
            "Provenance envelopes: every response carries source endpoint, UTC "
            "timestamp, and a computed flag for derived values.",
            "Verbatim errors: Pionex API errors pass through with original code/message.",
            "Audit log: every prepare/confirm/cancel is appended to "
            f"{SETTINGS.audit_log}.",
        ],
    })


# ---------------------------------------------------------------------------
# Register tool groups
# ---------------------------------------------------------------------------

from mcp_pionex.tools import market, account, trading, bots, earn  # noqa: E402

market.register(mcp)
account.register(mcp)
trading.register(mcp)
bots.register(mcp)
earn.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

"""
Pionex MCP server entry point.

Registers every tool group on an MCPServer instance and serves over stdio.
"""

from mcp.server.mcpserver import MCPServer

from mcp_pionex import __version__
from mcp_pionex.config import SETTINGS
from mcp_pionex import safety

INSTRUCTIONS = """
Pionex exchange MCP server: market data, technical analysis, account, spot
trading, spot/futures grid bots and Dual Investment.

STRICT ANTI-HALLUCINATION RULES — you MUST follow these:
1. NEVER state a price, balance, order status or any market fact without calling a
   tool first in this conversation turn. Your training data about crypto prices is
   always stale.
2. Only report values that literally appear inside the `data` field of a tool
   response. If a field is missing, say it is not available — do not fill gaps.
   Responses with `computed: true` are derived by this server (indicators,
   heuristics, portfolio maths), not facts published by the exchange.
3. Symbols use the exchange's exact format `BASE_QUOTE` (e.g. `BTC_USDT`;
   perpetuals are `BASE_QUOTE_PERP`). If unsure a symbol exists, call
   list_symbols or get_symbol_info first.
4. All state-changing actions (orders, bots, investments) are two-phase:
   `prepare_*` validates and returns a confirmation token; execution happens only
   via `confirm_action` with that exact token, after the human user explicitly
   approves the shown summary. Never fabricate, reuse or guess tokens.
5. Every prepared spot order carries a `client_order_id`. If a confirm_action
   response is lost, look the order up with get_order_by_client_id BEFORE
   preparing it again — never resubmit blindly.
6. Operator-set limits (capability gates, notional cap, price-deviation cap,
   leverage cap, symbol whitelist) are enforced server-side and CANNOT be changed
   from the conversation. If a guardrail blocks an action, tell the user which
   environment variable controls it.
7. Report API errors verbatim (code + message). Do not invent explanations.
"""

mcp = MCPServer("pionex", instructions=INSTRUCTIONS.strip(), version=__version__)


# ---------------------------------------------------------------------------
# Meta / introspection tools
# ---------------------------------------------------------------------------

@mcp.tool(annotations=safety.LOCAL)
def get_server_status() -> str:
    """Report the server's version, capability gates and active operator limits.

    Use this first in a session, or whenever another tool reports that it is
    disabled, to learn which features are on and which environment variable
    controls each limit. Purely local: no exchange request, no credentials
    needed.

    Returns `data` with: version, credentials_configured, trading_enabled,
    bots_enabled, futures_enabled, earn_enabled, max_order_notional,
    max_price_deviation_pct, max_leverage, symbol_whitelist,
    confirmation_ttl_seconds, pending_confirmations, audit_log."""
    return safety.envelope("mcp-pionex internal", {
        "version": __version__,
        "credentials_configured": SETTINGS.has_credentials,
        "trading_enabled": SETTINGS.trading_enabled,
        "bots_enabled": SETTINGS.bots_enabled,
        "futures_enabled": SETTINGS.futures_enabled,
        "earn_enabled": SETTINGS.earn_enabled,
        "max_order_notional": SETTINGS.max_order_notional,
        "max_price_deviation_pct": SETTINGS.max_price_deviation_pct,
        "max_leverage": SETTINGS.max_leverage,
        "symbol_whitelist": SETTINGS.symbol_whitelist or "all exchange symbols allowed",
        "confirmation_ttl_seconds": SETTINGS.confirmation_ttl,
        "pending_confirmations": safety.pending_count(),
        "audit_log": SETTINGS.audit_log,
    })


@mcp.tool(annotations=safety.LOCAL)
def get_safety_rules() -> str:
    """List every anti-hallucination and safety rule this server enforces.

    Use it to explain to the user why an action was blocked or why a value
    is unavailable. Purely local, no credentials needed.

    Returns `data.rules`: a list of human-readable rule statements including
    the currently configured numeric limits."""
    return safety.envelope("mcp-pionex internal", {
        "rules": [
            "Closed vocabularies: side, order type, interval, market type, grid type, "
            "trend, dual-investment type and close-sell model are validated against "
            "hardcoded whitelists.",
            "Live symbol verification: every symbol is checked against the exchange's "
            "current symbol list (10-min cache) before any request that uses it.",
            "Two-phase commit: state-changing actions require prepare_* followed by "
            "confirm_action with a single-use, parameter-bound, expiring token.",
            "Idempotency keys: every prepared spot order carries a clientOrderId "
            "(server-minted when not supplied) so it can be reconciled after a lost "
            "response.",
            "Notional cap per action: PIONEX_MCP_MAX_ORDER_NOTIONAL "
            f"(currently {SETTINGS.max_order_notional}).",
            "LIMIT price deviation guard: PIONEX_MCP_MAX_PRICE_DEVIATION_PCT "
            f"(currently {SETTINGS.max_price_deviation_pct}%) vs live mid-price.",
            "Leverage cap for futures grids: PIONEX_MCP_MAX_LEVERAGE "
            f"(currently {SETTINGS.max_leverage}x).",
            "Capability gates: trading / bots / futures / earn writes are off unless the "
            "operator sets PIONEX_MCP_TRADING_ENABLED / _BOTS_ENABLED / "
            "_FUTURES_ENABLED / _EARN_ENABLED.",
            "Optional symbol whitelist: PIONEX_MCP_SYMBOL_WHITELIST.",
            "Provenance envelopes: every response carries source endpoint, UTC "
            "timestamp, and a computed flag for derived values.",
            "MCP annotations: every tool declares readOnly/destructive/idempotent hints "
            "so clients can ask for human approval on destructive calls.",
            "Verbatim errors: Pionex API errors pass through with original code/message.",
            "Audit log: every prepare/confirm/cancel is appended to "
            f"{SETTINGS.audit_log}.",
        ],
    })


# ---------------------------------------------------------------------------
# Register tool groups
# ---------------------------------------------------------------------------

from mcp_pionex.tools import market, analysis, account, trading, bots, earn  # noqa: E402

market.register(mcp)
analysis.register(mcp)
account.register(mcp)
trading.register(mcp)
bots.register(mcp)
earn.register(mcp)


def main() -> None:
    """CLI entry point.

    Default transport is stdio (what Claude Code / Claude Desktop / Cursor
    spawn). ``--transport streamable-http`` serves the same server over HTTP
    at ``http://HOST:PORT/mcp`` for remote or multi-client setups; keep it on
    localhost or behind an authenticating reverse proxy — the exchange
    credentials live in this process.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="mcp-pionex",
                                     description="MCP server for Pionex")
    parser.add_argument("--transport", choices=("stdio", "streamable-http"),
                        default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--stateless", action="store_true",
                        help="stateless Streamable HTTP (no session ids); "
                             "note: pending confirmation tokens still live in "
                             "this process")
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run("streamable-http", host=args.host, port=args.port,
                stateless_http=args.stateless)


if __name__ == "__main__":
    main()

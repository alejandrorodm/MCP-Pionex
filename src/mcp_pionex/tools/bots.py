"""
Trading-bot tools (spot grid focus) — reads are open with credentials;
creation/cancellation is two-phase and gated behind PIONEX_MCP_BOTS_ENABLED.
"""

from mcp_pionex import safety
from mcp_pionex.actions import executor
from mcp_pionex.client import bot_client
from mcp_pionex.safety import guarded, require_bots, require_credentials, validate_enum


@executor("create_spot_grid")
def _execute_create_grid(params: dict) -> dict:
    require_bots()
    response = bot_client().create_spot_grid(
        base=params["base"], quote=params["quote"],
        buOrderData=params["buOrderData"],
    )
    return response.get("data", response)


@executor("cancel_spot_grid")
def _execute_cancel_grid(params: dict) -> dict:
    require_bots()
    response = bot_client().cancel_spot_grid(buOrderId=params["buOrderId"])
    return response.get("data", response)


def register(mcp):

    @mcp.tool()
    @guarded("GET /api/v1/bot/orders")
    def list_bot_orders(status: str = "", base: str = "", quote: str = "",
                        bot_types: str = "") -> dict:
        """List the account's trading bots. Optional filters: status (e.g.
        'RUNNING', 'FINISHED'), base/quote coin, bot_types comma-separated
        (e.g. 'SPOT_GRID,FUTURES_GRID')."""
        require_credentials()
        response = bot_client().list_orders(
            status=status or None, base=base or None, quote=quote or None,
            buOrderTypes=bot_types or None,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/bot/orders/spotGrid/order")
    def get_spot_grid(bu_order_id: str) -> dict:
        """Full state of one spot grid bot by its buOrderId: bounds, rows,
        investment, profit, status."""
        require_credentials()
        response = bot_client().get_spot_grid_order(buOrderId=bu_order_id)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/bot/orders/spotGrid/aiStrategy")
    def get_grid_ai_strategy(base: str, quote: str) -> dict:
        """Pionex's own AI-recommended grid parameters (top/bottom/row) for a
        pair. Use these exchange-provided numbers instead of inventing grid
        bounds."""
        require_credentials()
        response = bot_client().get_spot_grid_ai_strategy(base=base, quote=quote)
        return response["data"]

    @mcp.tool()
    @guarded("POST /api/v1/bot/orders/spotGrid/checkParams")
    def check_spot_grid_params(base: str, quote: str, top: str, bottom: str,
                               row: int, quote_investment: str,
                               grid_type: str = "arithmetic") -> dict:
        """Ask the EXCHANGE to validate spot-grid parameters without creating
        anything. Always run this before prepare_create_spot_grid — the
        exchange's verdict beats any local reasoning."""
        require_credentials()
        validate_enum(grid_type, safety.VALID_GRID_TYPES, "grid_type")
        data = bot_client().spot_grid_data(
            top=top, bottom=bottom, row=row,
            quoteTotalInvestment=quote_investment, gridType=grid_type,
        )
        response = bot_client().check_spot_grid_params(
            base=base, quote=quote, buOrderData=data,
        )
        return response.get("data", response)

    @mcp.tool()
    @guarded("validation only — no bot created")
    def prepare_create_spot_grid(base: str, quote: str, top: str, bottom: str,
                                 row: int, quote_investment: str,
                                 grid_type: str = "arithmetic") -> dict:
        """STEP 1 of 2 to create a spot grid bot. Validates locally (bounds,
        row 2-200, grid_type whitelist, notional cap) AND against the
        exchange's checkParams endpoint, then returns a confirmation token.
        Nothing is created until confirm_action with that token."""
        require_bots()
        validate_enum(grid_type, safety.VALID_GRID_TYPES, "grid_type")
        safety.require(2 <= int(row) <= 200, "row must be between 2 and 200")
        safety.require(float(top) > float(bottom) > 0,
                       "top must be greater than bottom, both positive")
        safety.check_notional_cap(float(quote_investment),
                                  "prepare_create_spot_grid")
        symbol = f"{base}_{quote}"
        safety.verify_symbol(symbol)

        data = bot_client().spot_grid_data(
            top=top, bottom=bottom, row=row,
            quoteTotalInvestment=quote_investment, gridType=grid_type,
        )
        check = bot_client().check_spot_grid_params(
            base=base, quote=quote, buOrderData=data,
        )
        summary = (
            f"Create SPOT GRID {base}/{quote}: range [{bottom}, {top}], "
            f"{row} rows ({grid_type}), invest {quote_investment} {quote}. "
            f"Exchange checkParams: {check.get('data', check)}"
        )
        return safety.prepare_action(
            "create_spot_grid",
            {"base": base, "quote": quote, "buOrderData": data},
            summary,
        )

    @mcp.tool()
    @guarded("validation only — bot not cancelled")
    def prepare_cancel_spot_grid(bu_order_id: str) -> dict:
        """STEP 1 of 2 to close a running spot grid bot. Fetches the bot's
        live state for the summary and returns a confirmation token."""
        require_bots()
        current = bot_client().get_spot_grid_order(buOrderId=bu_order_id)["data"]
        return safety.prepare_action(
            "cancel_spot_grid", {"buOrderId": bu_order_id},
            f"Close spot grid bot {bu_order_id}. Live state: {current}",
        )

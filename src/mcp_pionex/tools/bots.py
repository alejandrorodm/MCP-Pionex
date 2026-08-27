"""
Trading-bot tools: spot grid, futures grid and smart copy.

Reads are open with credentials. Every write is two-phase and gated:
spot grid behind PIONEX_MCP_BOTS_ENABLED; futures grid additionally behind
PIONEX_MCP_FUTURES_ENABLED and capped by PIONEX_MCP_MAX_LEVERAGE.
"""

from mcp_pionex import safety
from mcp_pionex.actions import executor
from mcp_pionex.client import bot_client
from mcp_pionex.safety import (
    PREPARE,
    READ,
    guarded,
    require_bots,
    require_credentials,
    require_futures,
    validate_enum,
)


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

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
    response = bot_client().cancel_spot_grid(
        buOrderId=params["buOrderId"],
        closeSellModel=params.get("closeSellModel"),
    )
    return response.get("data", response)


@executor("adjust_spot_grid")
def _execute_adjust_grid(params: dict) -> dict:
    require_bots()
    response = bot_client().adjust_spot_grid_params(**params)
    return response.get("data", response)


@executor("invest_in_spot_grid")
def _execute_invest_in_grid(params: dict) -> dict:
    require_bots()
    response = bot_client().invest_in_spot_grid(**params)
    return response.get("data", response)


@executor("extract_spot_grid_profit")
def _execute_extract_profit(params: dict) -> dict:
    require_bots()
    response = bot_client().extract_spot_grid_profit(**params)
    return response.get("data", response)


@executor("create_futures_grid")
def _execute_create_futures_grid(params: dict) -> dict:
    require_futures()
    safety.check_leverage(params["buOrderData"]["leverage"])
    response = bot_client().create_futures_grid(
        base=params["base"], quote=params["quote"],
        buOrderData=params["buOrderData"],
    )
    return response.get("data", response)


@executor("cancel_futures_grid")
def _execute_cancel_futures_grid(params: dict) -> dict:
    require_futures()
    response = bot_client().cancel_futures_grid(**params)
    return response.get("data", response)


def _perp_symbol(base: str, quote: str) -> str:
    """'BTC.PERP' + 'USDT' -> 'BTC_USDT_PERP' (the public symbol format)."""
    safety.require(
        base.endswith(".PERP"),
        f"Futures grid base must end with '.PERP' (e.g. 'BTC.PERP'), got {base!r}.",
    )
    return f"{base[:-5]}_{quote}_PERP"


def register(mcp):

    # ------------------------------------------------------------------ reads

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/bot/orders")
    def list_bot_orders(status: str = "", base: str = "", quote: str = "",
                        bot_types: str = "") -> dict:
        """List the account's trading bots (spot grid, futures grid, smart
        copy…) with optional filters.

        Use to discover buOrderIds before get_spot_grid / get_futures_grid
        or any prepare_* bot action — never guess an id.

        Args:
          status: optional, e.g. 'RUNNING' or 'FINISHED'.
          base / quote: optional coin filters (e.g. 'BTC', 'USDT').
          bot_types: optional comma-separated types, e.g.
            'SPOT_GRID,FUTURES_GRID'.

        Returns `data.orders`: list of bot objects (buOrderId, buOrderType,
        base, quote, status, investment, profit…), verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = bot_client().list_orders(
            status=status or None, base=base or None, quote=quote or None,
            buOrderTypes=bot_types or None,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/bot/orders/spotGrid/order")
    def get_spot_grid(bu_order_id: str) -> dict:
        """Return the full live state of one SPOT grid bot.

        Use before adjusting, topping up or closing a grid so the summary
        shown to the user reflects real bounds, rows, investment and profit.

        Args:
          bu_order_id: buOrderId from list_bot_orders.

        Returns the exchange's spot-grid object verbatim (top, bottom, row,
        gridType, quoteInvestment, totalProfit, status…). Requires API
        credentials (read)."""
        require_credentials()
        response = bot_client().get_spot_grid_order(buOrderId=bu_order_id)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/bot/orders/spotGrid/aiStrategy")
    def get_grid_ai_strategy(base: str, quote: str) -> dict:
        """Return Pionex's own AI-recommended spot-grid parameters (top,
        bottom, row) for a pair.

        Use these exchange-provided numbers as the starting point for
        prepare_create_spot_grid instead of inventing bounds.

        Args:
          base / quote: coins, e.g. 'BTC' and 'USDT'.

        Returns the exchange's recommendation object verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = bot_client().get_spot_grid_ai_strategy(base=base, quote=quote)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("POST /api/v1/bot/orders/spotGrid/checkParams")
    def check_spot_grid_params(base: str, quote: str, top: str, bottom: str,
                               row: int, quote_investment: str,
                               grid_type: str = "arithmetic") -> dict:
        """Ask the EXCHANGE to validate spot-grid parameters without creating
        anything.

        Run this before prepare_create_spot_grid — the exchange's verdict on
        minimum investment per grid, bounds and rows beats any local
        reasoning. Read-only despite being a POST.

        Args:
          base / quote: coins, e.g. 'BTC' and 'USDT'.
          top / bottom: price bounds as strings, top > bottom > 0.
          row: number of grid levels (2-200).
          quote_investment: total investment in quote currency, string.
          grid_type: 'arithmetic' or 'geometric'.

        Returns the exchange's checkParams response verbatim (including any
        rejection reason). Requires API credentials (read)."""
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

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/bot/orders/futuresGrid/order")
    def get_futures_grid(bu_order_id: str) -> dict:
        """Return the full live state of one FUTURES grid bot (leveraged).

        Use before closing a futures grid so the user sees real position,
        margin, leverage and P&L. For spot grids use get_spot_grid.

        Args:
          bu_order_id: buOrderId from list_bot_orders (bot_types
            'FUTURES_GRID').

        Returns the exchange's futures-grid object verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = bot_client().get_futures_grid_order(buOrderId=bu_order_id)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("POST /api/v1/bot/orders/futuresGrid/checkParams")
    def check_futures_grid_params(base: str, quote: str, top: str, bottom: str,
                                  row: int, quote_investment: str, leverage: int,
                                  trend: str = "no_trend",
                                  grid_type: str = "arithmetic") -> dict:
        """Ask the EXCHANGE to validate futures-grid parameters without
        creating anything. Also applies the operator leverage cap locally.

        Run this before prepare_create_futures_grid. Read-only despite being
        a POST.

        Args:
          base: perpetual base with suffix, e.g. 'BTC.PERP'. quote: 'USDT'.
          top / bottom: price bounds as strings, top > bottom > 0.
          row: grid levels (2-200).
          quote_investment: margin in quote currency, string.
          leverage: integer 1..PIONEX_MCP_MAX_LEVERAGE.
          trend: 'long', 'short' or 'no_trend'.
          grid_type: 'arithmetic' or 'geometric'.

        Returns the exchange's checkParams response verbatim. Requires API
        credentials (read); does not require the futures gate."""
        require_credentials()
        validate_enum(grid_type, safety.VALID_GRID_TYPES, "grid_type")
        validate_enum(trend, safety.VALID_TRENDS, "trend")
        safety.check_leverage(leverage)
        data = bot_client().futures_grid_data(
            top=top, bottom=bottom, row=row, quoteInvestment=quote_investment,
            leverage=leverage, trend=trend, grid_type=grid_type,
        )
        response = bot_client().check_futures_grid_params(
            base=base, quote=quote, buOrderData=data,
        )
        return response.get("data", response)

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/bot/orders/smartCopy/order")
    def get_smart_copy(bu_order_id: str) -> dict:
        """Return the live state of one Smart Copy (copy-trading) bot.

        Read-only: this server does not create or close smart-copy bots.

        Args:
          bu_order_id: buOrderId from list_bot_orders.

        Returns the exchange's smart-copy object verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = bot_client().get_smart_copy_order(buOrderId=bu_order_id)
        return response["data"]

    # -------------------------------------------------------- spot grid writes

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — no bot created")
    def prepare_create_spot_grid(base: str, quote: str, top: str, bottom: str,
                                 row: int, quote_investment: str,
                                 grid_type: str = "arithmetic") -> dict:
        """STEP 1 of 2 to create a SPOT grid bot. Validates locally (bounds,
        row 2-200, grid_type whitelist, notional cap, symbol existence) AND
        against the exchange's checkParams endpoint, then returns a
        confirmation token. Nothing is created until confirm_action.

        Use after get_grid_ai_strategy / check_spot_grid_params and show the
        summary (which embeds the exchange's verdict) to the user.

        Args:
          base / quote: coins, e.g. 'BTC' and 'USDT'.
          top / bottom: price bounds as strings, top > bottom > 0.
          row: grid levels (2-200).
          quote_investment: investment in quote currency, string; must be ≤
            PIONEX_MCP_MAX_ORDER_NOTIONAL.
          grid_type: 'arithmetic' or 'geometric'.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_BOTS_ENABLED=true."""
        require_bots()
        validate_enum(grid_type, safety.VALID_GRID_TYPES, "grid_type")
        safety.require(2 <= int(row) <= 200, "row must be between 2 and 200")
        safety.require(float(top) > float(bottom) > 0,
                       "top must be greater than bottom, both positive")
        safety.check_notional_cap(float(quote_investment),
                                  "prepare_create_spot_grid")
        safety.verify_symbol(f"{base}_{quote}")

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

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — bot not modified")
    def prepare_adjust_spot_grid(bu_order_id: str, top: str = "",
                                 bottom: str = "", row: int = 0,
                                 quote_invest: str = "") -> dict:
        """STEP 1 of 2 to modify a RUNNING spot grid bot's bounds, rows
        and/or investment. Returns a confirmation token; nothing changes
        until confirm_action.

        Use when the user wants to widen/narrow a grid or change its rows.
        To only add capital use prepare_invest_in_spot_grid. Fetches the
        bot's live state so the summary shows before → after.

        Args:
          bu_order_id: buOrderId from list_bot_orders.
          top / bottom: optional new bounds (strings); if both given,
            top > bottom > 0.
          row: optional new grid count (2-200); 0 = unchanged.
          quote_invest: optional new total investment (string); subject to
            PIONEX_MCP_MAX_ORDER_NOTIONAL.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_BOTS_ENABLED=true."""
        require_bots()
        params = {"buOrderId": bu_order_id}
        if top:
            params["top"] = top
        if bottom:
            params["bottom"] = bottom
        if top and bottom:
            safety.require(float(top) > float(bottom) > 0,
                           "top must be greater than bottom, both positive")
        if row:
            safety.require(2 <= int(row) <= 200, "row must be between 2 and 200")
            params["row"] = int(row)
        if quote_invest:
            safety.check_notional_cap(float(quote_invest), "prepare_adjust_spot_grid")
            params["quoteInvest"] = quote_invest
        safety.require(len(params) > 1,
                       "Provide at least one of top, bottom, row or quote_invest.")
        current = bot_client().get_spot_grid_order(buOrderId=bu_order_id)["data"]
        changes = {k: v for k, v in params.items() if k != "buOrderId"}
        return safety.prepare_action(
            "adjust_spot_grid", params,
            f"Adjust spot grid {bu_order_id}: {changes}. Live state before: {current}",
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing invested")
    def prepare_invest_in_spot_grid(bu_order_id: str, quote_invest: str) -> dict:
        """STEP 1 of 2 to ADD capital to a running spot grid bot. Returns a
        confirmation token; nothing is invested until confirm_action.

        Use for "put another 50 USDT into my BTC grid". The amount is capped
        by PIONEX_MCP_MAX_ORDER_NOTIONAL.

        Args:
          bu_order_id: buOrderId from list_bot_orders.
          quote_invest: amount to add in quote currency, string.

        Returns confirmation_token, validated_params and summary (with the
        bot's live state). Requires credentials and
        PIONEX_MCP_BOTS_ENABLED=true."""
        require_bots()
        safety.check_notional_cap(float(quote_invest), "prepare_invest_in_spot_grid")
        current = bot_client().get_spot_grid_order(buOrderId=bu_order_id)["data"]
        return safety.prepare_action(
            "invest_in_spot_grid",
            {"buOrderId": bu_order_id, "quoteInvest": quote_invest},
            f"Add {quote_invest} (quote) to spot grid {bu_order_id}. Live state: {current}",
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing withdrawn")
    def prepare_extract_spot_grid_profit(bu_order_id: str, amount: str) -> dict:
        """STEP 1 of 2 to WITHDRAW realised profit from a running spot grid
        bot without closing it. Returns a confirmation token.

        Use for "take 20 USDT of profit out of the grid". The amount is
        checked against the bot's live profit figure.

        Args:
          bu_order_id: buOrderId from list_bot_orders.
          amount: profit to withdraw in quote currency, string, > 0.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_BOTS_ENABLED=true."""
        require_bots()
        safety.require(float(amount) > 0, "amount must be positive")
        current = bot_client().get_spot_grid_order(buOrderId=bu_order_id)["data"]
        available = current.get("totalProfit") or current.get("profit")
        if available is not None:
            safety.require(
                float(amount) <= float(available),
                f"Requested {amount} exceeds the bot's live profit {available}.",
            )
        return safety.prepare_action(
            "extract_spot_grid_profit",
            {"buOrderId": bu_order_id, "amount": amount},
            f"Withdraw {amount} profit from spot grid {bu_order_id} "
            f"(live profit: {available}).",
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — bot not cancelled")
    def prepare_cancel_spot_grid(bu_order_id: str,
                                 close_sell_model: str = "") -> dict:
        """STEP 1 of 2 to CLOSE a running spot grid bot. Fetches the bot's
        live state for the summary and returns a confirmation token.

        Use when the user wants to stop a grid. Ask whether to sell the
        base coin on close or keep it.

        Args:
          bu_order_id: buOrderId from list_bot_orders.
          close_sell_model: optional 'SELL' (convert base to quote on close)
            or 'HOLD' (keep the base coin); empty = exchange default.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_BOTS_ENABLED=true."""
        require_bots()
        params = {"buOrderId": bu_order_id}
        if close_sell_model:
            validate_enum(close_sell_model, safety.VALID_CLOSE_SELL_MODELS,
                          "close_sell_model")
            params["closeSellModel"] = close_sell_model
        current = bot_client().get_spot_grid_order(buOrderId=bu_order_id)["data"]
        return safety.prepare_action(
            "cancel_spot_grid", params,
            f"Close spot grid bot {bu_order_id}"
            f"{' (' + close_sell_model + ' base on close)' if close_sell_model else ''}. "
            f"Live state: {current}",
        )

    # ----------------------------------------------------- futures grid writes

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — no bot created")
    def prepare_create_futures_grid(base: str, quote: str, top: str, bottom: str,
                                    row: int, quote_investment: str,
                                    leverage: int, trend: str = "no_trend",
                                    grid_type: str = "arithmetic") -> dict:
        """STEP 1 of 2 to create a FUTURES (perpetual, leveraged) grid bot.
        Validates locally (bounds, rows, leverage ≤ PIONEX_MCP_MAX_LEVERAGE,
        margin ≤ notional cap, perpetual symbol existence) AND against the
        exchange's checkParams, then returns a confirmation token.

        Leverage multiplies both profit and loss and can liquidate the
        margin. Make the user acknowledge leverage and trend explicitly
        before confirm_action.

        Args:
          base: perpetual base with suffix, e.g. 'BTC.PERP'. quote: 'USDT'.
          top / bottom: price bounds as strings, top > bottom > 0.
          row: grid levels (2-200).
          quote_investment: margin in quote currency, string; ≤
            PIONEX_MCP_MAX_ORDER_NOTIONAL.
          leverage: integer 1..PIONEX_MCP_MAX_LEVERAGE.
          trend: 'long', 'short' or 'no_trend'.
          grid_type: 'arithmetic' or 'geometric'.

        Returns confirmation_token, validated_params and summary embedding
        the exchange verdict. Requires credentials,
        PIONEX_MCP_BOTS_ENABLED=true AND PIONEX_MCP_FUTURES_ENABLED=true."""
        require_futures()
        validate_enum(grid_type, safety.VALID_GRID_TYPES, "grid_type")
        validate_enum(trend, safety.VALID_TRENDS, "trend")
        safety.check_leverage(leverage)
        safety.require(2 <= int(row) <= 200, "row must be between 2 and 200")
        safety.require(float(top) > float(bottom) > 0,
                       "top must be greater than bottom, both positive")
        safety.check_notional_cap(float(quote_investment),
                                  "prepare_create_futures_grid")
        safety.verify_symbol(_perp_symbol(base, quote), market_type="PERP")

        data = bot_client().futures_grid_data(
            top=top, bottom=bottom, row=row, quoteInvestment=quote_investment,
            leverage=leverage, trend=trend, grid_type=grid_type,
        )
        check = bot_client().check_futures_grid_params(
            base=base, quote=quote, buOrderData=data,
        )
        summary = (
            f"Create FUTURES GRID {base}/{quote} {trend} x{leverage}: range "
            f"[{bottom}, {top}], {row} rows ({grid_type}), margin "
            f"{quote_investment} {quote}. Exchange checkParams: "
            f"{check.get('data', check)}"
        )
        return safety.prepare_action(
            "create_futures_grid",
            {"base": base, "quote": quote, "buOrderData": data},
            summary,
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — bot not cancelled")
    def prepare_cancel_futures_grid(bu_order_id: str,
                                    immediate: bool = False) -> dict:
        """STEP 1 of 2 to CLOSE a running futures grid bot and its position.
        Fetches the live state for the summary and returns a confirmation
        token.

        Args:
          bu_order_id: buOrderId from list_bot_orders (FUTURES_GRID).
          immediate: true to close the position at market immediately
            (default false = exchange default close behaviour).

        Returns confirmation_token, validated_params and summary. Requires
        credentials, PIONEX_MCP_BOTS_ENABLED=true and
        PIONEX_MCP_FUTURES_ENABLED=true."""
        require_futures()
        params = {"buOrderId": bu_order_id}
        if immediate:
            params["immediate"] = True
        current = bot_client().get_futures_grid_order(buOrderId=bu_order_id)["data"]
        return safety.prepare_action(
            "cancel_futures_grid", params,
            f"Close futures grid bot {bu_order_id}"
            f"{' immediately at market' if immediate else ''}. Live state: {current}",
        )

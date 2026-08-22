"""
Spot trading tools — all writes are two-phase (prepare -> confirm).

Gated behind PIONEX_MCP_TRADING_ENABLED. Every prepared order is validated
against live exchange data (symbol existence, precision, minimums, live
price) and capped by operator limits before a confirmation token is issued.
"""

from mcp_pionex import safety
from mcp_pionex.actions import EXECUTORS, executor
from mcp_pionex.client import orders_client, trade_client
from mcp_pionex.safety import (
    guarded,
    require_trading,
    validate_enum,
    verify_symbol,
)


# ---------------------------------------------------------------------------
# Executors (run only via confirm_action with a valid token)
# ---------------------------------------------------------------------------

@executor("place_order")
def _execute_order(params: dict) -> dict:
    require_trading()
    response = orders_client().new_order(**params)
    return response["data"]


@executor("cancel_all_orders")
def _execute_cancel_all(params: dict) -> dict:
    require_trading()
    response = orders_client().cancel_all_orders(symbol=params["symbol"])
    return response.get("data", response)


@executor("rebalance")
def _execute_rebalance(params: dict) -> list:
    require_trading()
    return trade_client().execute_rebalance(params["plan"], dry_run=False)


def register(mcp):

    @mcp.tool()
    @guarded("validation only — no order sent")
    def prepare_order(symbol: str, side: str, order_type: str,
                      size: str = "", price: str = "", amount: str = "",
                      client_order_id: str = "", ioc: bool = False) -> str:
        """STEP 1 of 2 to place a spot order. Validates everything against
        live exchange data and returns a confirmation token — NO order is sent.

        Parameters (all numeric values as strings, exactly as they should
        reach the exchange):
        - side: 'BUY' or 'SELL'. order_type: 'LIMIT' or 'MARKET'.
        - LIMIT: requires price + size (base units).
        - MARKET BUY: requires amount (quote currency to spend, e.g. USDT).
        - MARKET SELL: requires size (base units to sell).

        After this returns, show the summary to the user and only call
        confirm_action with the token once they explicitly approve."""
        require_trading()
        validate_enum(side, safety.VALID_SIDES, "side")
        validate_enum(order_type, safety.VALID_ORDER_TYPES, "order_type")
        info = verify_symbol(symbol)

        params = {"symbol": symbol, "side": side, "type": order_type}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        if ioc:
            params["IOC"] = True

        reference_price = None
        if order_type == "LIMIT":
            safety.require(bool(price) and bool(size),
                           "LIMIT orders require both price and size")
            price_f, size_f = float(price), float(size)
            reference_price = safety.check_price_deviation(symbol, price_f)
            notional = price_f * size_f
            params["price"], params["size"] = price, size
        elif side == "BUY":
            safety.require(bool(amount),
                           "MARKET BUY requires amount (quote currency to spend)")
            notional = float(amount)
            params["amount"] = amount
        else:
            safety.require(bool(size),
                           "MARKET SELL requires size (base units to sell)")
            size_f = float(size)
            from mcp_pionex.client import markets_client
            reference_price = markets_client().get_price(symbol)
            notional = size_f * reference_price

        safety.check_notional_cap(notional, "prepare_order")

        min_notional = float(info.get("minAmount") or 0)
        if min_notional and notional < min_notional:
            raise safety.SafetyError(
                f"Order notional {notional:.4f} is below the exchange minimum "
                f"{min_notional} for {symbol} (minAmount from live symbol info)."
            )

        summary = (
            f"{side} {order_type} on {symbol}: "
            + (f"size={size} @ price={price}" if order_type == "LIMIT"
               else (f"spend amount={amount} (quote)" if side == "BUY"
                     else f"sell size={size} (base)"))
            + f" | est. notional ≈ {notional:.4f}"
            + (f" | live ref price {reference_price}" if reference_price else "")
        )
        return safety.envelope(
            "validation only — no order sent",
            safety.prepare_action("place_order", params, summary),
        )

    @mcp.tool()
    @guarded("validation only — nothing cancelled")
    def prepare_cancel_all_orders(symbol: str) -> dict:
        """STEP 1 of 2 to cancel EVERY open order on a symbol. Returns a
        confirmation token; nothing is cancelled until confirm_action."""
        require_trading()
        verify_symbol(symbol)
        open_orders = orders_client().get_open_orders(symbol=symbol)["data"]
        count = len(open_orders.get("orders", open_orders) or [])
        return safety.prepare_action(
            "cancel_all_orders", {"symbol": symbol},
            f"Cancel ALL open orders on {symbol} (currently {count} open)",
        )

    @mcp.tool()
    @guarded("DELETE /api/v1/trade/order")
    def cancel_order(symbol: str, order_id: int) -> dict:
        """Cancel ONE specific open order by orderId. Direct (no token needed):
        cancelling a single identified order is low-risk and reversible in
        effect. The order_id must come from get_open_orders or a prior
        placement — never from memory."""
        require_trading()
        verify_symbol(symbol)
        response = orders_client().cancel_order(symbol=symbol, orderId=order_id)
        safety.audit("execute", "cancel_order",
                     {"symbol": symbol, "orderId": order_id})
        return response.get("data", response)

    @mcp.tool()
    @guarded("balances + live prices (computed plan)")
    def compute_rebalance_plan(target_weights_json: str,
                               threshold: float = 0.01) -> str:
        """Compute (dry-run, nothing executed) the MARKET orders needed to move
        the portfolio to target weights. target_weights_json is a JSON object
        like {"BTC": 0.5, "ETH": 0.3, "USDT": 0.2} — fractions summing to ~1.0.
        threshold: minimum weight drift before an order is generated.
        Review the plan, then use prepare_rebalance to get a confirmation token."""
        import json as _json
        safety.require_credentials()
        target = _json.loads(target_weights_json)
        plan = trade_client().compute_rebalance_orders(target, threshold=threshold)
        rounded = trade_client().execute_rebalance(plan, dry_run=True)
        return safety.envelope(
            "computed from live balances and prices",
            {"orders": rounded, "count": len(rounded)},
            computed=True,
            note="dry run — nothing was executed; sizes already rounded to exchange precision",
        )

    @mcp.tool()
    @guarded("validation only — nothing executed")
    def prepare_rebalance(target_weights_json: str,
                          threshold: float = 0.01) -> dict:
        """STEP 1 of 2 to EXECUTE a portfolio rebalance as MARKET orders.
        Recomputes the plan from live data, checks every order against the
        notional cap, and returns a confirmation token plus the exact plan
        that will run. Show the plan to the user before confirming."""
        import json as _json
        require_trading()
        target = _json.loads(target_weights_json)
        plan = trade_client().compute_rebalance_orders(target, threshold=threshold)
        for order in plan:
            notional = abs(order.get("delta_value", 0.0))
            safety.check_notional_cap(notional, f"rebalance {order['symbol']}")
        summary = "; ".join(
            f"{o['side']} {o['symbol']} ≈ {abs(o['delta_value']):.2f}"
            for o in plan
        ) or "no orders needed (within threshold)"
        return safety.prepare_action("rebalance", {"plan": plan}, summary)

    @mcp.tool()
    @guarded("execution of a previously prepared action")
    def confirm_action(confirmation_token: str) -> str:
        """STEP 2 of 2: execute a previously prepared action (order, cancel-all,
        rebalance, bot or investment) using its single-use token. Only call
        this after the human user has explicitly approved the summary shown by
        the prepare_* tool. The parameters executed are the ones stored at
        prepare time — nothing can be changed here."""
        entry = safety.take_pending(confirmation_token)
        action, params = entry["action"], entry["params"]
        fn = EXECUTORS.get(action)
        safety.require(fn is not None, f"No executor registered for {action!r}")
        result = fn(params)
        safety.audit("execute", action,
                     {"token": confirmation_token, "params": params,
                      "result": result})
        return safety.envelope(
            f"executed prepared action: {action}",
            {"action": action, "executed_params": params, "result": result},
        )

"""
Spot trading tools — all writes are two-phase (prepare -> confirm).

Gated behind PIONEX_MCP_TRADING_ENABLED. Every prepared order is validated
against live exchange data (symbol existence, precision, minimums, live
price) and capped by operator limits before a confirmation token is issued.
Every prepared order also carries a clientOrderId (server-minted if the
caller does not supply one) so it can be reconciled after a lost response.
"""

from mcp_pionex import safety
from mcp_pionex.actions import EXECUTORS, executor
from mcp_pionex.client import markets_client, orders_client, trade_client
from mcp_pionex.safety import (
    EXECUTE,
    PREPARE,
    READ,
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


@executor("cancel_orders")
def _execute_cancel_orders(params: dict) -> list:
    require_trading()
    return orders_client().cancel_orders(
        symbol=params["symbol"], orderIds=params["orderIds"],
    )


@executor("rebalance")
def _execute_rebalance(params: dict) -> list:
    require_trading()
    return trade_client().execute_rebalance(params["plan"], dry_run=False)


def register(mcp):

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — no order sent")
    def prepare_order(symbol: str, side: str, order_type: str,
                      size: str = "", price: str = "", amount: str = "",
                      client_order_id: str = "", ioc: bool = False) -> str:
        """STEP 1 of 2 to place a spot order: validate it against live
        exchange data and return a confirmation token. NO order is sent.

        Use for any buy/sell request. Then show the returned summary to the
        user and call confirm_action with the token only after they
        explicitly approve. For portfolio-wide rebalancing use
        compute_rebalance_plan / prepare_rebalance instead.

        Validation performed: side/order_type whitelist, symbol existence
        and operator whitelist, LIMIT price within
        PIONEX_MCP_MAX_PRICE_DEVIATION_PCT of the live mid-price, notional ≤
        PIONEX_MCP_MAX_ORDER_NOTIONAL and ≥ the exchange minimum.

        Args (numeric values as strings, exactly as they reach the exchange):
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          side: 'BUY' or 'SELL'. order_type: 'LIMIT' or 'MARKET'.
          size: base units — required for LIMIT and MARKET SELL.
          price: required for LIMIT.
          amount: quote currency to spend — required for MARKET BUY.
          client_order_id: optional idempotency key (1-32 chars
            [A-Za-z0-9_-]); the server mints one ('mcp-…') if empty.
          ioc: immediate-or-cancel flag for LIMIT orders.

        Returns `data` with confirmation_token, client_order_id,
        validated_params, summary and expires_in_seconds. The token is
        single-use and expires (PIONEX_MCP_CONFIRMATION_TTL). Requires API
        credentials and PIONEX_MCP_TRADING_ENABLED=true."""
        require_trading()
        validate_enum(side, safety.VALID_SIDES, "side")
        validate_enum(order_type, safety.VALID_ORDER_TYPES, "order_type")
        info = verify_symbol(symbol)
        coid = safety.client_order_id(client_order_id)

        params = {"symbol": symbol, "side": side, "type": order_type,
                  "clientOrderId": coid}
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
            reference_price = markets_client().get_price(symbol)
            notional = size_f * reference_price
            params["size"] = size

        safety.check_notional_cap(notional, "prepare_order")

        min_notional = float(info.get("minAmount") or info.get("minNotional") or 0)
        if min_notional and notional < min_notional:
            raise safety.SafetyError(
                f"Order notional {notional:.4f} is below the exchange minimum "
                f"{min_notional} for {symbol} (from live symbol info)."
            )

        summary = (
            f"{side} {order_type} on {symbol}: "
            + (f"size={size} @ price={price}" if order_type == "LIMIT"
               else (f"spend amount={amount} (quote)" if side == "BUY"
                     else f"sell size={size} (base)"))
            + f" | est. notional ≈ {notional:.4f}"
            + (f" | live ref price {reference_price}" if reference_price else "")
            + f" | client_order_id={coid}"
        )
        prepared = safety.prepare_action("place_order", params, summary)
        prepared["client_order_id"] = coid
        prepared["reconcile_with"] = (
            "get_order_by_client_id if the confirm_action response is lost"
        )
        return safety.envelope("validation only — no order sent", prepared)

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing cancelled")
    def prepare_cancel_all_orders(symbol: str) -> dict:
        """STEP 1 of 2 to cancel EVERY open spot order on one symbol. Returns
        a confirmation token; nothing is cancelled until confirm_action.

        Use when the user wants to clear the whole book on a pair. To cancel
        one order use cancel_order (direct); for a chosen subset use
        prepare_cancel_orders.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.

        Returns confirmation_token, summary (includes the live count of open
        orders) and expires_in_seconds. Requires credentials and
        PIONEX_MCP_TRADING_ENABLED=true."""
        require_trading()
        verify_symbol(symbol)
        open_orders = orders_client().get_open_orders(symbol=symbol)["data"]
        count = len(open_orders.get("orders", open_orders) or [])
        return safety.prepare_action(
            "cancel_all_orders", {"symbol": symbol},
            f"Cancel ALL open orders on {symbol} (currently {count} open)",
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing cancelled")
    def prepare_cancel_orders(symbol: str, order_ids: str) -> dict:
        """STEP 1 of 2 to cancel a specific LIST of open spot orders on one
        symbol. Returns a confirmation token; nothing is cancelled until
        confirm_action.

        Use when the user picks several (but not all) orders to cancel. Each
        id is checked against the live open-order list first, so a stale or
        invented orderId is rejected before anything runs. For one order use
        cancel_order; for all use prepare_cancel_all_orders.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          order_ids: comma-separated numeric orderIds from get_open_orders.

        Returns confirmation_token, validated_params (the resolved id list)
        and summary. Execution cancels ids one by one and reports per-id
        results. Requires credentials and PIONEX_MCP_TRADING_ENABLED=true."""
        require_trading()
        verify_symbol(symbol)
        ids = []
        for piece in order_ids.split(","):
            piece = piece.strip()
            safety.require(piece.isdigit(), f"orderId {piece!r} is not numeric")
            ids.append(int(piece))
        safety.require(1 <= len(ids) <= 50, "provide between 1 and 50 orderIds")
        open_orders = orders_client().get_open_orders(symbol=symbol)["data"]
        live = {int(o["orderId"]) for o in (open_orders.get("orders") or [])}
        missing = [i for i in ids if i not in live]
        safety.require(
            not missing,
            f"orderIds {missing} are not open on {symbol} right now. Use "
            f"get_open_orders and pass ids from that response only.",
        )
        return safety.prepare_action(
            "cancel_orders", {"symbol": symbol, "orderIds": ids},
            f"Cancel {len(ids)} open order(s) on {symbol}: {ids}",
        )

    @mcp.tool(annotations=EXECUTE)
    @guarded("DELETE /api/v1/trade/order")
    def cancel_order(symbol: str, order_id: int) -> dict:
        """Cancel ONE specific open spot order by orderId — executes
        immediately (no confirmation token).

        Cancelling a single identified order is low-risk and cannot spend
        funds, so it is the one write that skips the two-phase flow. For
        several orders use prepare_cancel_orders; for all use
        prepare_cancel_all_orders.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          order_id: numeric orderId from get_open_orders or a prior
            confirm_action result — never from memory.

        Returns the exchange's cancel response verbatim; an already-closed
        order yields a verbatim API error. Logged to the audit trail.
        Requires credentials and PIONEX_MCP_TRADING_ENABLED=true."""
        require_trading()
        verify_symbol(symbol)
        response = orders_client().cancel_order(symbol=symbol, orderId=order_id)
        safety.audit("execute", "cancel_order",
                     {"symbol": symbol, "orderId": order_id})
        return response.get("data", response)

    @mcp.tool(annotations=READ)
    @guarded("balances + live prices (computed plan)")
    def compute_rebalance_plan(target_weights_json: str,
                               threshold: float = 0.01) -> str:
        """Compute — without executing anything — the MARKET orders needed
        to move the portfolio to a set of target weights.

        Use to preview a rebalance and discuss it with the user. When they
        agree, call prepare_rebalance (which recomputes from live data) and
        then confirm_action. Always a dry run.

        Args:
          target_weights_json: JSON object of coin → fraction, e.g.
            {"BTC": 0.5, "ETH": 0.3, "USDT": 0.2}; fractions should sum to
            ~1.0.
          threshold: minimum absolute weight drift before an order is
            generated (default 0.01 = 1 %).

        Returns `data.orders` (symbol, side, size/amount rounded to
        exchange precision, delta_value) and `count`. computed=true from
        live balances and prices. Requires API credentials (read)."""
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

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing executed")
    def prepare_rebalance(target_weights_json: str,
                          threshold: float = 0.01) -> dict:
        """STEP 1 of 2 to EXECUTE a portfolio rebalance as MARKET orders.
        Recomputes the plan from live data, checks every order against
        PIONEX_MCP_MAX_ORDER_NOTIONAL and returns a confirmation token plus
        the exact plan that will run.

        Use only after the user has reviewed compute_rebalance_plan. Show
        the plan again before confirm_action.

        Args:
          target_weights_json: JSON object coin → fraction (see
            compute_rebalance_plan).
          threshold: minimum weight drift before an order is generated.

        Returns confirmation_token, validated_params.plan and summary.
        Requires credentials and PIONEX_MCP_TRADING_ENABLED=true."""
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

    @mcp.tool(annotations=EXECUTE)
    @guarded("execution of a previously prepared action")
    def confirm_action(confirmation_token: str) -> str:
        """STEP 2 of 2: execute a previously prepared action using its
        single-use confirmation token. This is the ONLY tool that changes
        exchange state for orders, rebalances, bots and investments.

        Call it only after the human user has explicitly approved the
        summary shown by the prepare_* tool. The parameters executed are the
        ones stored server-side at prepare time — nothing can be altered
        here. A used, unknown or expired token is rejected; prepare again
        to get a fresh one. If the response is lost, reconcile with
        get_order_by_client_id (orders) or the relevant get_* tool before
        re-preparing.

        Args:
          confirmation_token: exact token string from a prepare_* response.

        Returns `data` with action, executed_params and the exchange's
        result verbatim (e.g. orderId). Logged to the audit trail. Requires
        the capability gate of the underlying action."""
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

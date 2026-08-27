"""Read-only account tools. Need API credentials but work in read-only mode."""

from mcp_pionex import safety
from mcp_pionex.client import account_client, orders_client, trade_client
from mcp_pionex.safety import READ, guarded, require_credentials, verify_symbol


def register(mcp):

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/account/balances")
    def get_balances(include_zero: bool = False) -> dict:
        """Return the account's spot balances per coin (free, frozen, total).

        Use for "how much X do I have". For balances valued in a quote
        currency with weights use get_portfolio. Balances are live account
        facts — never estimate them.

        Args:
          include_zero: include coins with zero balance (default false).

        Returns `data` as a mapping coin → {free, frozen, total} (floats).
        Requires API credentials with read permission; works in read-only
        mode."""
        require_credentials()
        return account_client().get_balance_dict(include_zero=include_zero)

    @mcp.tool(annotations=READ)
    @guarded("balances + live prices (computed)")
    def get_portfolio(quote: str = "USDT") -> str:
        """Return a whole-portfolio view valued in a quote currency: per-coin
        amount, live price, value and weight, plus the total.

        Use for allocation questions ("what % is BTC?") and before
        compute_rebalance_plan. For raw balances use get_balances.

        Args:
          quote: valuation currency (default 'USDT').

        Returns `data` with total_value and `positions` (sorted by value:
        coin, amount, price, value, weight). computed=true: value = amount ×
        live price, weight = value / total_value. Requires API credentials
        (read)."""
        require_credentials()
        stats = trade_client().get_portfolio_stats()
        return safety.envelope(
            "GET /api/v1/account/balances + /api/v1/market/bookTickers",
            stats,
            computed=True,
            note="value = total * live price; weight = value / total_value",
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/openOrders")
    def get_open_orders(symbol: str) -> dict:
        """Return the account's currently open (unfilled) spot orders for a
        symbol.

        Use to find orderIds before cancel_order / prepare_cancel_orders,
        or to check what is resting on the book. For closed orders use
        get_order_history.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.

        Returns `data.orders`: list of order objects (orderId, clientOrderId,
        side, type, price, size, filledSize, status, createTime ms),
        verbatim. Requires API credentials (read)."""
        require_credentials()
        verify_symbol(symbol)
        response = orders_client().get_open_orders(symbol=symbol)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/order")
    def get_order(order_id: int) -> dict:
        """Return the details of one spot order by its numeric orderId.

        Use to check status (OPEN/CLOSED), filled size, average price and
        fee of a known order. If you only have the client id use
        get_order_by_client_id.

        Args:
          order_id: numeric exchange orderId from get_open_orders,
            get_order_history or a confirm_action result — never from
            memory.

        Returns the exchange's order object verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = orders_client().get_order(orderId=order_id)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/orderByClientOrderId")
    def get_order_by_client_id(client_order_id: str) -> dict:
        """Return one spot order by the clientOrderId it was created with.

        Use to RECONCILE an order whose confirm_action response was lost or
        timed out: every prepare_order returns a `client_order_id`; look it
        up here before ever re-preparing the same order.

        Args:
          client_order_id: the id shown by prepare_order (e.g.
            'mcp-1a2b3c4d5e6f') or one supplied by the user.

        Returns the exchange's order object verbatim, or a verbatim API error
        if no order with that id exists (meaning it was never placed).
        Requires API credentials (read)."""
        require_credentials()
        response = orders_client().get_order_by_client_order_id(
            clientOrderId=client_order_id,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/allOrders")
    def get_order_history(symbol: str, limit: int = 50,
                          start_time_ms: int = 0, end_time_ms: int = 0) -> dict:
        """Return the account's historical (open and closed) spot orders for
        a symbol.

        Use for past activity, P&L reconstruction or audit. For only the
        resting orders use get_open_orders; for executions use get_fills.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          limit: orders to return, 1-200 (default 50).
          start_time_ms / end_time_ms: optional epoch-ms range (0 = unset).

        Returns `data.orders`: list of order objects verbatim, newest first.
        Requires API credentials (read)."""
        require_credentials()
        safety.require(1 <= limit <= 200, "limit must be between 1 and 200")
        verify_symbol(symbol)
        response = orders_client().get_all_orders(
            symbol=symbol, limit=limit,
            startTime=start_time_ms or None, endTime=end_time_ms or None,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/fills")
    def get_fills(symbol: str, start_time_ms: int = 0, end_time_ms: int = 0) -> dict:
        """Return the account's recent trade fills (executions) for a symbol
        — latest 100.

        Use for realised prices, fees and maker/taker role. For the fills of
        one specific order use get_fills_by_order.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          start_time_ms / end_time_ms: optional epoch-ms range (0 = unset).

        Returns `data.fills`: list of {id, orderId, symbol, side, role, price,
        size, fee, feeCoin, timestamp ms}, verbatim. Requires API credentials
        (read)."""
        require_credentials()
        verify_symbol(symbol)
        response = orders_client().get_fills(
            symbol=symbol,
            startTime=start_time_ms or None, endTime=end_time_ms or None,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/trade/fillsByOrderId")
    def get_fills_by_order(order_id: int) -> dict:
        """Return every fill belonging to one spot order.

        Use to compute the real average entry price and total fee of a
        filled order from exchange data instead of estimating.

        Args:
          order_id: numeric exchange orderId (from get_order,
            get_open_orders or a confirm_action result).

        Returns `data.fills`: list of fill objects verbatim. Requires API
        credentials (read)."""
        require_credentials()
        response = orders_client().get_fills_by_order_id(orderId=order_id)
        return response["data"]

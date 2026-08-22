"""Read-only account tools. Need API credentials but work in read-only mode."""

from mcp_pionex import safety
from mcp_pionex.client import account_client, orders_client, trade_client
from mcp_pionex.safety import guarded, require_credentials, verify_symbol


def register(mcp):

    @mcp.tool()
    @guarded("GET /api/v1/account/balances")
    def get_balances(include_zero: bool = False) -> dict:
        """Account balances per coin: free, frozen and total. Requires API
        credentials (read permission). Balances are live account facts — never
        estimate them."""
        require_credentials()
        return account_client().get_balance_dict(include_zero=include_zero)

    @mcp.tool()
    @guarded("balances + live prices (computed)")
    def get_portfolio(quote: str = "USDT") -> str:
        """Whole-portfolio view valued in the quote currency: per-coin amount,
        live price, value and weight, sorted by value, plus the total. Prices
        are fetched live; `value` and `weight` are computed from them."""
        require_credentials()
        stats = trade_client().get_portfolio_stats()
        return safety.envelope(
            "GET /api/v1/account/balances + /api/v1/market/bookTickers",
            stats,
            computed=True,
            note="value = total * live price; weight = value / total_value",
        )

    @mcp.tool()
    @guarded("GET /api/v1/trade/openOrders")
    def get_open_orders(symbol: str) -> dict:
        """Currently open (unfilled) spot orders for a symbol."""
        require_credentials()
        verify_symbol(symbol)
        response = orders_client().get_open_orders(symbol=symbol)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/trade/order")
    def get_order(order_id: int) -> dict:
        """Details of one order by its numeric orderId: status (OPEN/CLOSED),
        filled size, average price, fee."""
        require_credentials()
        response = orders_client().get_order(orderId=order_id)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/trade/orderByClientOrderId")
    def get_order_by_client_id(client_order_id: str) -> dict:
        """Details of one order by the clientOrderId string it was created with."""
        require_credentials()
        response = orders_client().get_order_by_client_order_id(
            clientOrderId=client_order_id,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/trade/allOrders")
    def get_order_history(symbol: str, limit: int = 50,
                          start_time_ms: int = 0, end_time_ms: int = 0) -> dict:
        """Historical orders for a symbol (default 50, max 200). Optional
        epoch-ms time range."""
        require_credentials()
        safety.require(1 <= limit <= 200, "limit must be between 1 and 200")
        verify_symbol(symbol)
        response = orders_client().get_all_orders(
            symbol=symbol, limit=limit,
            startTime=start_time_ms or None, endTime=end_time_ms or None,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/trade/fills")
    def get_fills(symbol: str, start_time_ms: int = 0, end_time_ms: int = 0) -> dict:
        """Recent trade fills (executions) for a symbol — latest 100, with
        price, size, fee and role (taker/maker)."""
        require_credentials()
        verify_symbol(symbol)
        response = orders_client().get_fills(
            symbol=symbol,
            startTime=start_time_ms or None, endTime=end_time_ms or None,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/trade/fillsByOrderId")
    def get_fills_by_order(order_id: int) -> dict:
        """All fills belonging to one order — use to compute the real average
        entry price of a filled order from exchange data."""
        require_credentials()
        response = orders_client().get_fills_by_order_id(orderId=order_id)
        return response["data"]

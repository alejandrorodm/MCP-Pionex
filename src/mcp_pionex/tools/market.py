"""Public market-data tools. No credentials needed; always enabled."""

from mcp_pionex import safety
from mcp_pionex.client import common_client, markets_client
from mcp_pionex.safety import guarded, validate_enum, verify_symbol


def register(mcp):

    @mcp.tool()
    @guarded("GET /api/v1/common/symbols")
    def list_symbols(market_type: str = "SPOT", search: str = "") -> dict:
        """List real trading symbols on Pionex, exactly as the exchange spells
        them (format BASE_QUOTE, e.g. 'BTC_USDT'). market_type: 'SPOT' or
        'PERP'. Optional case-insensitive `search` substring filter.
        Use this instead of guessing symbol names."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        symbols = common_client().list_symbols(market_type=market_type)
        if search:
            needle = search.upper()
            symbols = [s for s in symbols if needle in s]
        return {"market_type": market_type, "count": len(symbols), "symbols": symbols}

    @mcp.tool()
    @guarded("GET /api/v1/common/symbols")
    def get_symbol_info(symbol: str, market_type: str = "SPOT") -> dict:
        """Exchange metadata for one symbol: precision (base/quote/amount),
        minimum trade size, minimum notional, enabled status. Call this before
        sizing any order — precision and minimums come from here, never from
        memory."""
        info = verify_symbol(symbol, market_type)
        return info

    @mcp.tool()
    @guarded("GET /api/v1/market/bookTickers + /api/v1/market/tickers")
    def get_price(symbol: str, market_type: str = "SPOT") -> str:
        """Live mid-price ((best bid + best ask) / 2) for a symbol, falling
        back to last traded price for illiquid pairs. This is the ONLY valid
        source for a current price — never quote prices from memory."""
        verify_symbol(symbol, market_type)
        price = markets_client().get_price(symbol, market_type=market_type)
        return safety.envelope(
            "GET /api/v1/market/bookTickers",
            {"symbol": symbol, "market_type": market_type, "mid_price": price},
            computed=True,
            note="mid_price is computed as (bid+ask)/2 from live book-ticker data",
        )

    @mcp.tool()
    @guarded("GET /api/v1/market/tickers")
    def get_ticker_24h(symbol: str = "", market_type: str = "SPOT") -> dict:
        """24-hour rolling stats (open/close/high/low/volume/amount/count) for
        one symbol, or for every symbol if `symbol` is empty."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        if symbol:
            verify_symbol(symbol, market_type)
        response = markets_client().get_24hr_ticker(
            symbol=symbol or None, type=market_type,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/market/bookTickers")
    def get_book_ticker(symbol: str = "", market_type: str = "SPOT") -> dict:
        """Best bid/ask (price and size) for one symbol, or all symbols if
        `symbol` is empty."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        if symbol:
            verify_symbol(symbol, market_type)
        response = markets_client().get_book_ticker(
            symbol=symbol or None, type=market_type,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/market/depth")
    def get_depth(symbol: str, limit: int = 20) -> dict:
        """Order book (bids/asks) for a symbol. limit range 1-1000, default 20.
        Each level is [price, size] as strings, verbatim from the exchange."""
        safety.require(1 <= limit <= 1000, "limit must be between 1 and 1000")
        verify_symbol(symbol)
        response = markets_client().get_depth(symbol=symbol, limit=limit)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/market/trades")
    def get_recent_trades(symbol: str, limit: int = 100) -> dict:
        """Recent public trades for a symbol. limit range 10-500, default 100."""
        safety.require(10 <= limit <= 500, "limit must be between 10 and 500")
        verify_symbol(symbol)
        response = markets_client().get_trades(symbol=symbol, limit=limit)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/market/klines")
    def get_klines(symbol: str, interval: str, limit: int = 100,
                   end_time_ms: int = 0) -> dict:
        """Candlesticks for a symbol. interval MUST be one of: 1M, 5M, 15M,
        30M, 60M, 4H, 8H, 12H, 1D (these exact strings). limit 1-500, default
        100. end_time_ms: optional epoch-milliseconds upper bound (0 = now).
        Times in the response are epoch milliseconds."""
        validate_enum(interval, safety.VALID_KLINE_INTERVALS, "interval")
        safety.require(1 <= limit <= 500, "limit must be between 1 and 500")
        verify_symbol(symbol)
        response = markets_client().get_klines(
            symbol=symbol, interval=interval,
            endTime=end_time_ms or None, limit=limit,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/market/klines (paged)")
    def get_klines_history(symbol: str, interval: str, total: int,
                           end_time_ms: int = 0) -> str:
        """Fetch MORE than 500 candles by paging backwards through history.
        Returns a flat oldest-first list. Use for backtests/long lookbacks;
        capped at 5000 candles per call."""
        validate_enum(interval, safety.VALID_KLINE_INTERVALS, "interval")
        safety.require(1 <= total <= 5000, "total must be between 1 and 5000")
        verify_symbol(symbol)
        klines = markets_client().get_klines_history(
            symbol=symbol, interval=interval, total=total,
            endTime=end_time_ms or None,
        )
        return safety.envelope(
            "GET /api/v1/market/klines (paged)",
            {"symbol": symbol, "interval": interval,
             "count": len(klines), "klines": klines},
            computed=True,
            note="pages of raw klines concatenated oldest-first; values verbatim",
        )

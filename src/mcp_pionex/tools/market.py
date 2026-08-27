"""Public market-data tools. No credentials needed; always enabled."""

from mcp_pionex import safety
from mcp_pionex.client import common_client, markets_client
from mcp_pionex.safety import READ, guarded, validate_enum, verify_symbol


def register(mcp):

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/common/symbols")
    def list_symbols(market_type: str = "SPOT", search: str = "") -> dict:
        """List the trading symbols that exist on Pionex right now, spelled
        exactly as the exchange spells them.

        Use this instead of guessing a symbol name, and before any tool that
        takes a `symbol`. For metadata about one symbol use get_symbol_info.

        Args:
          market_type: 'SPOT' (e.g. 'BTC_USDT') or 'PERP' (e.g. 'BTC_USDT_PERP').
          search: optional case-insensitive substring filter (e.g. 'BTC').

        Returns `data` with market_type, count and `symbols` (list of strings).
        Public endpoint — no credentials. Cached 10 minutes server-side."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        symbols = common_client().list_symbols(market_type=market_type)
        if search:
            needle = search.upper()
            symbols = [s for s in symbols if needle in s]
        return {"market_type": market_type, "count": len(symbols), "symbols": symbols}

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/common/symbols")
    def get_symbol_info(symbol: str, market_type: str = "SPOT") -> dict:
        """Return exchange metadata for one symbol: precision, minimum sizes,
        minimum notional and trading status.

        Call this before sizing an order — precision and minimums come from
        here, never from memory. Fails with a 'did you mean' hint if the
        symbol does not exist.

        Args:
          symbol: exact exchange symbol, e.g. 'BTC_USDT'.
          market_type: 'SPOT' or 'PERP'.

        Returns the exchange's symbol object verbatim (basePrecision,
        quotePrecision, minAmount/minNotional, baseStep, status, ...).
        Public endpoint — no credentials."""
        info = verify_symbol(symbol, market_type)
        return info

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/bookTickers + /api/v1/market/tickers")
    def get_price(symbol: str, market_type: str = "SPOT") -> str:
        """Return the live mid-price of a symbol: (best bid + best ask) / 2,
        falling back to the last traded price for illiquid pairs.

        This is the ONLY valid source for a current price — never quote
        prices from memory. Use get_book_ticker for raw bid/ask and
        get_ticker_24h for daily statistics.

        Args:
          symbol: exact exchange symbol, e.g. 'BTC_USDT'.
          market_type: 'SPOT' or 'PERP'.

        Returns `data` with symbol, market_type and `mid_price` (float).
        Marked computed=true because the mid-price is derived from the book.
        Public endpoint — no credentials."""
        verify_symbol(symbol, market_type)
        price = markets_client().get_price(symbol, market_type=market_type)
        return safety.envelope(
            "GET /api/v1/market/bookTickers",
            {"symbol": symbol, "market_type": market_type, "mid_price": price},
            computed=True,
            note="mid_price is computed as (bid+ask)/2 from live book-ticker data",
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/tickers")
    def get_ticker_24h(symbol: str = "", market_type: str = "SPOT") -> dict:
        """Return 24-hour rolling statistics (open, close, high, low, volume,
        amount, trade count) for one symbol or for every symbol.

        Use for daily change, volume ranking or volatility screening. For the
        current price prefer get_price.

        Args:
          symbol: exact exchange symbol, or empty for all symbols (large).
          market_type: 'SPOT' or 'PERP'.

        Returns the exchange's ticker list verbatim under `data.tickers`.
        Public endpoint — no credentials."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        if symbol:
            verify_symbol(symbol, market_type)
        response = markets_client().get_24hr_ticker(
            symbol=symbol or None, type=market_type,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/bookTickers")
    def get_book_ticker(symbol: str = "", market_type: str = "SPOT") -> dict:
        """Return the best bid and best ask (price and size) for one symbol
        or for every symbol.

        Use when you need the spread or top-of-book liquidity; use get_depth
        for deeper levels and get_price for a single mid-price.

        Args:
          symbol: exact exchange symbol, or empty for all symbols.
          market_type: 'SPOT' or 'PERP'.

        Returns the exchange's book-ticker list verbatim (bidPrice, bidSize,
        askPrice, askSize as strings). Public endpoint — no credentials."""
        validate_enum(market_type, safety.VALID_MARKET_TYPES, "market_type")
        if symbol:
            verify_symbol(symbol, market_type)
        response = markets_client().get_book_ticker(
            symbol=symbol or None, type=market_type,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/depth")
    def get_depth(symbol: str, limit: int = 20) -> dict:
        """Return the order book (bids and asks) for a spot symbol.

        Use for liquidity and slippage estimation before sizing a large
        order. For just the top of book use get_book_ticker.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          limit: number of levels per side, 1-1000 (default 20).

        Returns `data.bids` and `data.asks`: lists of [price, size] string
        pairs, verbatim from the exchange, best price first.
        Public endpoint — no credentials."""
        safety.require(1 <= limit <= 1000, "limit must be between 1 and 1000")
        verify_symbol(symbol)
        response = markets_client().get_depth(symbol=symbol, limit=limit)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/trades")
    def get_recent_trades(symbol: str, limit: int = 100) -> dict:
        """Return the most recent public trades (prints) for a spot symbol.

        Use to see actual executed prices and taker direction; not the
        account's own fills (use get_fills for those).

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          limit: number of trades, 10-500 (default 100).

        Returns `data.trades`: list of trades with price, size, side and
        timestamp (epoch ms), verbatim. Public endpoint — no credentials."""
        safety.require(10 <= limit <= 500, "limit must be between 10 and 500")
        verify_symbol(symbol)
        response = markets_client().get_trades(symbol=symbol, limit=limit)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines")
    def get_klines(symbol: str, interval: str, limit: int = 100,
                   end_time_ms: int = 0) -> dict:
        """Return raw candlesticks (OHLCV) for a spot symbol — up to 500 per
        call.

        Use for charting or your own calculations. For pre-computed
        indicators use get_indicators / get_emas; for more than 500 candles
        use get_klines_history.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          limit: candles to return, 1-500 (default 100).
          end_time_ms: optional epoch-ms upper bound; 0 means now.

        Returns `data.klines`: list of {time, open, high, low, close, volume}
        with times in epoch ms and prices as strings, verbatim.
        Public endpoint — no credentials."""
        validate_enum(interval, safety.VALID_KLINE_INTERVALS, "interval")
        safety.require(1 <= limit <= 500, "limit must be between 1 and 500")
        verify_symbol(symbol)
        response = markets_client().get_klines(
            symbol=symbol, interval=interval,
            endTime=end_time_ms or None, limit=limit,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines (paged)")
    def get_klines_history(symbol: str, interval: str, total: int,
                           end_time_ms: int = 0) -> str:
        """Fetch a long candlestick history (more than 500 candles) by paging
        backwards through the klines endpoint.

        Use for backtests or long lookbacks; for ≤500 candles get_klines is
        cheaper (one request). Each 500 candles costs one API call.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          total: candles wanted, 1-5000.
          end_time_ms: optional epoch-ms upper bound; 0 means now.

        Returns `data.klines`: flat oldest-first list of candle objects and
        `count`. Marked computed=true only because pages are concatenated;
        values are verbatim. Public endpoint — no credentials."""
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

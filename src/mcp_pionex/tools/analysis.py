"""
Technical analysis over live exchange candles.

Everything produced here is DERIVED: deterministic formulas/heuristics
(mcp_pionex.ta) applied to klines fetched live. Every response is marked
`computed: true` and carries a note with the exact definition and its
parameters, so the model can cite the method and never present a heuristic
detection as an exchange fact.
"""

from mcp_pionex import safety, ta
from mcp_pionex.client import markets_client
from mcp_pionex.safety import READ, guarded, validate_enum, verify_symbol

_MAX_LOOKBACK = 500
_MIN_CANDLES = 30


def _candles(symbol: str, interval: str, limit: int) -> list:
    validate_enum(interval, safety.VALID_KLINE_INTERVALS, "interval")
    safety.require(_MIN_CANDLES <= limit <= _MAX_LOOKBACK,
                   f"limit must be between {_MIN_CANDLES} and {_MAX_LOOKBACK}")
    verify_symbol(symbol)
    raw = markets_client().get_klines(
        symbol=symbol, interval=interval, limit=limit,
    )["data"]["klines"]
    candles = ta.parse_klines(raw)
    safety.require(
        len(candles) >= _MIN_CANDLES,
        f"Only {len(candles)} candles available for {symbol} {interval}; "
        f"need at least {_MIN_CANDLES} for analysis.",
    )
    return candles


def _last(series: list):
    for value in reversed(series):
        if value is not None:
            return value
    return None


def _round(value):
    return None if value is None else round(value, 8)


def register(mcp):

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines + EMA (computed)")
    def get_emas(symbol: str, interval: str, periods: str = "20,50,200",
                 limit: int = 500) -> str:
        """Compute the current value of one or more EMAs (exponential moving
        averages) from live candle closes, and where the price sits relative
        to each.

        Use for trend-following context ("is price above the 200 EMA?").
        For a full indicator panel (RSI, MACD, ATR, Bollinger) use
        get_indicators instead; this tool exists to pick custom periods.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          periods: comma-separated integers 2-400 (default "20,50,200").
          limit: candles to fetch, 30-500 (default 500). A period needs at
            least that many candles or its value is null.

        Returns `data.emas` keyed "EMA<n>" → {value, price_above,
        distance_pct} plus last_close, last_candle_time (epoch ms) and
        candles_used. computed=true: standard EMA (SMA seed, k=2/(n+1)).
        Public — no credentials."""
        period_list = []
        for piece in periods.split(","):
            piece = piece.strip()
            safety.require(piece.isdigit() and 2 <= int(piece) <= 400,
                           f"invalid EMA period {piece!r} (must be 2-400)")
            period_list.append(int(piece))
        candles = _candles(symbol, interval, limit)
        closes = [c["close"] for c in candles]
        price = closes[-1]
        emas = {}
        for period in period_list:
            value = _last(ta.ema(closes, period))
            emas[f"EMA{period}"] = None if value is None else {
                "value": round(value, 8),
                "price_above": price > value,
                "distance_pct": round((price - value) / value * 100.0, 4),
            }
        return safety.envelope(
            "GET /api/v1/market/klines + EMA (computed)",
            {"symbol": symbol, "interval": interval,
             "candles_used": len(candles), "last_close": price,
             "last_candle_time": candles[-1]["time"], "emas": emas},
            computed=True,
            note=("Standard EMA (SMA seed, k=2/(n+1)) over the closes of "
                  f"{len(candles)} live candles. null = not enough candles "
                  "for that period."),
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines + indicators (computed)")
    def get_indicators(symbol: str, interval: str, limit: int = 500) -> str:
        """Compute a panel of classic indicators from live candles: RSI(14),
        MACD(12,26,9), ATR(14), Bollinger Bands(20,2) and SMA/EMA 20/50/200 —
        latest values only.

        Use as the default one-call market snapshot before discussing
        momentum, volatility or trend. For custom EMA periods use get_emas;
        for price-action structures use detect_fvg, detect_order_blocks or
        get_market_structure.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          limit: candles to fetch, 30-500 (default 500). SMA/EMA 200 need
            ≥200 candles or they are null.

        Returns `data` with rsi_14, macd_12_26_9 {line, signal, histogram},
        atr_14, bollinger_20_2 {upper, middle, lower}, sma{}, ema{},
        last_close, last_candle_time (epoch ms), candles_used.
        computed=true with standard formulas (Wilder RSI/ATR). Public — no
        credentials."""
        candles = _candles(symbol, interval, limit)
        closes = [c["close"] for c in candles]
        macd_result = ta.macd(closes)
        boll = ta.bollinger(closes)
        data = {
            "symbol": symbol, "interval": interval,
            "candles_used": len(candles),
            "last_close": closes[-1],
            "last_candle_time": candles[-1]["time"],
            "rsi_14": _round(_last(ta.rsi(closes, 14))),
            "macd_12_26_9": {
                "line": _round(_last(macd_result["line"])),
                "signal": _round(_last(macd_result["signal"])),
                "histogram": _round(_last(macd_result["histogram"])),
            },
            "atr_14": _round(_last(ta.atr(candles, 14))),
            "bollinger_20_2": {
                "upper": _round(_last(boll["upper"])),
                "middle": _round(_last(boll["middle"])),
                "lower": _round(_last(boll["lower"])),
            },
            "sma": {f"SMA{p}": _round(_last(ta.sma(closes, p)))
                    for p in (20, 50, 200)},
            "ema": {f"EMA{p}": _round(_last(ta.ema(closes, p)))
                    for p in (20, 50, 200)},
        }
        return safety.envelope(
            "GET /api/v1/market/klines + indicators (computed)",
            data,
            computed=True,
            note=("Standard formulas: Wilder RSI, MACD = EMA12-EMA26 with EMA9 "
                  "signal, Wilder ATR, Bollinger SMA20 ± 2σ. null = not enough "
                  "candles."),
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines + FVG heuristic (computed)")
    def detect_fvg(symbol: str, interval: str, lookback: int = 200,
                   min_gap_pct: float = 0.0, only_open: bool = True) -> str:
        """Detect Fair Value Gaps (3-candle imbalances) on live candles and
        report whether each gap is still open, partially filled or filled.

        Use when the user asks about imbalances, unfilled gaps or
        "FVG" zones as potential reaction areas. For supply/demand candles
        use detect_order_blocks; for swing trend use get_market_structure.
        This is a HEURISTIC computed by the server, not exchange data.

        Definition: bullish FVG when low[i+1] > high[i-1] (zone
        [high[i-1], low[i+1]]); bearish is symmetric.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          lookback: candles to scan, 30-500 (default 200).
          min_gap_pct: ignore gaps smaller than this % of price, 0-10
            (default 0 = keep all).
          only_open: true (default) omits gaps already fully filled.

        Returns `data.fvgs`: list of {direction, top, bottom, formed_at
        (epoch ms), status: open|partially_filled|filled}, plus
        total_detected, returned, last_close and candles_used.
        computed=true. Public — no credentials."""
        safety.require(0.0 <= min_gap_pct <= 10.0,
                       "min_gap_pct must be between 0 and 10")
        candles = _candles(symbol, interval, lookback)
        gaps = ta.detect_fvg(candles, min_gap_pct=min_gap_pct)
        total = len(gaps)
        if only_open:
            gaps = [g for g in gaps if g["status"] != "filled"]
        return safety.envelope(
            "GET /api/v1/market/klines + FVG heuristic (computed)",
            {"symbol": symbol, "interval": interval,
             "candles_used": len(candles), "last_close": candles[-1]["close"],
             "total_detected": total, "returned": len(gaps), "fvgs": gaps},
            computed=True,
            note=("3-candle definition: bullish if low[i+1] > high[i-1] "
                  "(zone [high[i-1], low[i+1]]); bearish symmetric. Status "
                  "evaluated against candles after formation. Timestamps in "
                  "epoch ms."),
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines + order-block heuristic (computed)")
    def detect_order_blocks(symbol: str, interval: str, lookback: int = 200,
                            displacement_factor: float = 1.5,
                            only_unmitigated: bool = False) -> str:
        """Detect order blocks — the last opposing candle before an impulsive
        move — on live candles, and classify each as fresh, mitigated or
        broken.

        Use when the user asks for supply/demand zones or "order blocks" as
        potential reaction areas. For 3-candle imbalances use detect_fvg;
        for swing-based trend use get_market_structure. This is a HEURISTIC
        computed by the server; other order-block definitions will yield
        different zones.

        Definition: a candle whose body |close-open| exceeds
        displacement_factor × ATR(14) marks an impulse; the order block is
        the last opposing-colour candle among the 3 before it, zone
        [low, high]. fresh = price has not returned; mitigated = price
        traded into the zone; broken = a close beyond the far side.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          lookback: candles to scan, 30-500 (default 200); at least ~30 are
            needed for a stable ATR.
          displacement_factor: impulse threshold in ATR multiples, 0.5-5
            (default 1.5; higher = fewer, stronger blocks).
          only_unmitigated: true returns only `fresh` blocks (default false
            returns all with their status).

        Returns `data.order_blocks`: list of {direction: bullish|bearish,
        top, bottom, formed_at (epoch ms), status}, plus total_detected,
        returned, last_close, candles_used and displacement_factor.
        computed=true. Public — no credentials."""
        safety.require(0.5 <= displacement_factor <= 5.0,
                       "displacement_factor must be between 0.5 and 5")
        candles = _candles(symbol, interval, lookback)
        blocks = ta.detect_order_blocks(
            candles, displacement_factor=displacement_factor,
        )
        total = len(blocks)
        if only_unmitigated:
            blocks = [b for b in blocks if b["status"] == "fresh"]
        return safety.envelope(
            "GET /api/v1/market/klines + order-block heuristic (computed)",
            {"symbol": symbol, "interval": interval,
             "candles_used": len(candles), "last_close": candles[-1]["close"],
             "displacement_factor": displacement_factor,
             "total_detected": total, "returned": len(blocks),
             "order_blocks": blocks},
            computed=True,
            note=("Displacement = |close-open| > factor × Wilder ATR(14). "
                  "OB = last opposing candle within the 3 before the impulse, "
                  "zone [low, high]. broken = close beyond the far side. "
                  "Timestamps in epoch ms."),
        )

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/market/klines + swing structure (computed)")
    def get_market_structure(symbol: str, interval: str, lookback: int = 200,
                             swing_strength: int = 2) -> str:
        """Identify swing highs/lows on live candles, label them HH/LH/HL/LL
        and derive a trend reading (uptrend, downtrend or range).

        Use when the user asks whether a market is trending or ranging, or
        for recent swing levels. For indicator-based momentum use
        get_indicators; for zones use detect_fvg / detect_order_blocks.
        This is a HEURISTIC computed by the server.

        Definition: a swing high is a candle whose high strictly exceeds the
        highs of `swing_strength` candles on each side (fractal); swing lows
        symmetric. Labels compare each swing with the previous swing of the
        same kind; the trend is read from the last 4 labels.

        Args:
          symbol: exact spot symbol, e.g. 'BTC_USDT'.
          interval: exactly one of 1M, 5M, 15M, 30M, 60M, 4H, 8H, 12H, 1D.
          lookback: candles to scan, 30-500 (default 200).
          swing_strength: candles required on each side, 1-10 (default 2;
            higher = fewer, more significant swings).

        Returns `data` with trend, swing_count, `swings` (last 20:
        {kind: high|low, label: HH|LH|HL|LL, price, time epoch ms}),
        last_close and candles_used. computed=true. Public — no
        credentials."""
        safety.require(1 <= swing_strength <= 10,
                       "swing_strength must be between 1 and 10")
        candles = _candles(symbol, interval, lookback)
        structure = ta.market_structure(candles, strength=swing_strength)
        return safety.envelope(
            "GET /api/v1/market/klines + swing structure (computed)",
            {"symbol": symbol, "interval": interval,
             "candles_used": len(candles), "last_close": candles[-1]["close"],
             "swing_strength": swing_strength,
             "trend": structure["trend"],
             "swing_count": len(structure["swings"]),
             "swings": structure["swings"][-20:]},
            computed=True,
            note=("Fractal: swing high if its high strictly exceeds the "
                  f"{swing_strength} candles on each side (symmetric for lows). "
                  "Labels vs the previous swing of the same kind. Last 20 "
                  "swings returned. Timestamps in epoch ms."),
        )

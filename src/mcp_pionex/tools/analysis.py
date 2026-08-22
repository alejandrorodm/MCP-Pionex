"""
Análisis técnico sobre velas reales del exchange.

Todo lo que sale de aquí es DERIVADO: se calcula con fórmulas/heurísticas
deterministas (mcp_pionex.ta) sobre klines obtenidas en vivo. Cada respuesta
va marcada `computed: true` y lleva una nota con la definición exacta y sus
parámetros, para que el modelo pueda citar el método y nunca presente una
detección heurística como un hecho del exchange.
"""

from mcp_pionex import safety, ta
from mcp_pionex.client import markets_client
from mcp_pionex.safety import guarded, validate_enum, verify_symbol

_MAX_LOOKBACK = 500


def _candles(symbol: str, interval: str, limit: int) -> list:
    validate_enum(interval, safety.VALID_KLINE_INTERVALS, "interval")
    safety.require(30 <= limit <= _MAX_LOOKBACK,
                   f"limit must be between 30 and {_MAX_LOOKBACK}")
    verify_symbol(symbol)
    raw = markets_client().get_klines(
        symbol=symbol, interval=interval, limit=limit,
    )["data"]["klines"]
    candles = ta.parse_klines(raw)
    safety.require(
        len(candles) >= 30,
        f"Only {len(candles)} candles available for {symbol} {interval}; "
        f"need at least 30 for analysis.",
    )
    return candles


def _last(series: list):
    for value in reversed(series):
        if value is not None:
            return value
    return None


def register(mcp):

    @mcp.tool()
    @guarded("GET /api/v1/market/klines + EMA (computed)")
    def get_emas(symbol: str, interval: str, periods: str = "20,50,200",
                 limit: int = 500) -> str:
        """Valores actuales de EMAs sobre cierres de velas reales.
        `periods`: lista separada por comas (p. ej. "20,50,200"). Devuelve por
        periodo el valor de la EMA, si el precio está por encima, y la
        distancia en %. DERIVADO de klines vivas — no es un dato del exchange."""
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
            note=("EMA estándar (semilla SMA, k=2/(n+1)) sobre cierres de "
                  f"{len(candles)} velas reales. None = velas insuficientes "
                  "para ese periodo."),
        )

    @mcp.tool()
    @guarded("GET /api/v1/market/klines + indicators (computed)")
    def get_indicators(symbol: str, interval: str, limit: int = 500) -> str:
        """Panel de indicadores clásicos sobre velas reales: RSI(14),
        MACD(12,26,9), ATR(14), Bollinger(20,2) y SMA/EMA 20/50/200 — últimos
        valores. DERIVADO de klines vivas con fórmulas estándar."""
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
            note=("Fórmulas estándar: RSI de Wilder, MACD EMA12-EMA26 con señal "
                  "EMA9, ATR de Wilder, Bollinger SMA20±2σ. None = velas "
                  "insuficientes."),
        )

    @mcp.tool()
    @guarded("GET /api/v1/market/klines + FVG heuristic (computed)")
    def detect_fvg(symbol: str, interval: str, lookback: int = 200,
                   min_gap_pct: float = 0.0, only_open: bool = True) -> str:
        """Fair Value Gaps (definición de 3 velas) sobre velas reales:
        FVG alcista cuando low[i+1] > high[i-1]; bajista cuando
        high[i+1] < low[i-1]. Cada gap incluye zona [bottom, top], timestamp
        de formación y estado (open / partially_filled / filled).
        `only_open=True` omite los ya rellenados. `min_gap_pct` filtra huecos
        menores a ese % del precio. HEURÍSTICA computada, no un hecho del
        exchange."""
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
            note=("Definición 3-velas: bullish si low[i+1] > high[i-1] "
                  "(zona [high[i-1], low[i+1]]); bearish simétrico. Estado "
                  "evaluado con las velas posteriores a la formación. "
                  "Timestamps en ms epoch."),
        )

    @mcp.tool()
    @guarded("GET /api/v1/market/klines + order-block heuristic (computed)")
    def detect_order_blocks(symbol: str, interval: str, lookback: int = 200,
                            displacement_factor: float = 1.5,
                            only_unmitigated: bool = False) -> str:
        """Order blocks sobre velas reales, heurística de desplazamiento:
        una vela con cuerpo > displacement_factor × ATR(14) marca impulso;
        el order block es la última vela contraria en las 3 previas
        (zona [low, high]). Estado: fresh / mitigated / broken.
        HEURÍSTICA computada — otras definiciones de OB darán zonas distintas."""
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
            note=("Desplazamiento = |close-open| > factor × ATR(14) de Wilder. "
                  "OB = última vela contraria en las 3 previas al impulso, "
                  "zona [low, high]. broken = cierre más allá del lado opuesto. "
                  "Timestamps en ms epoch."),
        )

    @mcp.tool()
    @guarded("GET /api/v1/market/klines + swing structure (computed)")
    def get_market_structure(symbol: str, interval: str, lookback: int = 200,
                             swing_strength: int = 2) -> str:
        """Estructura de mercado sobre velas reales: puntos de giro (fractales
        de `swing_strength` velas por lado) etiquetados HH/LH/HL/LL, y lectura
        de tendencia (uptrend/downtrend/range) de las últimas 4 etiquetas.
        HEURÍSTICA computada."""
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
            note=("Fractal: swing high si su high supera estrictamente a las "
                  f"{swing_strength} velas de cada lado (simétrico para lows). "
                  "Etiquetas frente al swing previo del mismo tipo. Se "
                  "devuelven los últimos 20 swings. Timestamps en ms epoch."),
        )


def _round(value):
    return None if value is None else round(value, 8)

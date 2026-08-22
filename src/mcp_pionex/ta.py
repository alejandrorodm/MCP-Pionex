"""
Análisis técnico puro (sin red, sin dependencias externas).

Todas las funciones operan sobre listas de velas normalizadas
({time, open, high, low, close, volume} con floats, orden antiguo→reciente)
y son deterministas: mismos datos, mismo resultado. Las tools de
`tools/analysis.py` las envuelven con procedencia `computed: true` y una nota
con la definición exacta usada — un FVG o un order block son HEURÍSTICAS
sobre datos reales del exchange, no hechos del exchange.
"""

from statistics import pstdev


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def parse_klines(raw: list) -> list:
    """Convierte las klines crudas de Pionex (strings, orden reciente→antiguo)
    en velas float ordenadas antiguo→reciente."""
    candles = [
        {
            "time": int(k["time"]),
            "open": float(k["open"]),
            "high": float(k["high"]),
            "low": float(k["low"]),
            "close": float(k["close"]),
            "volume": float(k.get("volume", 0) or 0),
        }
        for k in raw
    ]
    candles.sort(key=lambda c: c["time"])
    return candles


# ---------------------------------------------------------------------------
# Medias e indicadores clásicos
# ---------------------------------------------------------------------------

def sma(values: list, period: int) -> list:
    """SMA simple; None hasta tener `period` datos."""
    out = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            out[i] = running / period
    return out


def ema(values: list, period: int) -> list:
    """EMA estándar: semilla = SMA de las primeras `period`, k = 2/(period+1)."""
    out = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2.0 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list, period: int = 14) -> list:
    """RSI de Wilder."""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains) + 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """MACD clásico: línea = EMA(fast) - EMA(slow); señal = EMA(signal) de la línea."""
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    line = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    defined = [v for v in line if v is not None]
    signal_defined = ema(defined, signal)
    signal_line = [None] * len(line)
    j = 0
    for i, v in enumerate(line):
        if v is not None:
            signal_line[i] = signal_defined[j]
            j += 1
    hist = [
        (l - s) if (l is not None and s is not None) else None
        for l, s in zip(line, signal_line)
    ]
    return {"line": line, "signal": signal_line, "histogram": hist}


def atr(candles: list, period: int = 14) -> list:
    """ATR de Wilder sobre True Range."""
    out = [None] * len(candles)
    if len(candles) <= period:
        return out
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(
            c["high"] - c["low"],
            abs(c["high"] - p["close"]),
            abs(c["low"] - p["close"]),
        ))
    value = sum(trs[:period]) / period
    out[period] = value
    for i in range(period + 1, len(candles)):
        value = (value * (period - 1) + trs[i - 1]) / period
        out[i] = value
    return out


def bollinger(closes: list, period: int = 20, mult: float = 2.0) -> dict:
    """Bandas de Bollinger: SMA(period) ± mult * desviación típica poblacional."""
    mid = sma(closes, period)
    upper = [None] * len(closes)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        dev = pstdev(closes[i - period + 1:i + 1])
        upper[i] = mid[i] + mult * dev
        lower[i] = mid[i] - mult * dev
    return {"middle": mid, "upper": upper, "lower": lower}


# ---------------------------------------------------------------------------
# Smart Money Concepts (heurísticas)
# ---------------------------------------------------------------------------

def detect_fvg(candles: list, min_gap_pct: float = 0.0) -> list:
    """
    Fair Value Gaps con la definición de 3 velas:

        - FVG alcista en la vela i (media de la tríada i-1, i, i+1) cuando
          low[i+1] > high[i-1]. Zona = [high[i-1], low[i+1]].
        - FVG bajista cuando high[i+1] < low[i-1]. Zona = [high[i+1], low[i-1]].

    Estado según el precio posterior a la formación:
        open              nada ha tocado la zona
        partially_filled  el precio entró en la zona sin cruzarla entera
        filled            el precio atravesó la zona completa (mitigado)

    min_gap_pct filtra huecos menores a ese % del precio medio de la zona.
    """
    gaps = []
    for i in range(1, len(candles) - 1):
        prev, mid, nxt = candles[i - 1], candles[i], candles[i + 1]
        zone = None
        if nxt["low"] > prev["high"]:
            zone = ("bullish", prev["high"], nxt["low"])
        elif nxt["high"] < prev["low"]:
            zone = ("bearish", nxt["high"], prev["low"])
        if zone is None:
            continue
        side, bottom, top = zone
        mid_price = (top + bottom) / 2.0
        size_pct = (top - bottom) / mid_price * 100.0
        if size_pct < min_gap_pct:
            continue
        gaps.append({
            "type": side,
            "formed_at": mid["time"],
            "candle_index": i,
            "top": top,
            "bottom": bottom,
            "size_pct": round(size_pct, 4),
            "status": "open",
            "filled_at": None,
        })

    # Estado: recorrer velas posteriores a la formación (desde i+2)
    for gap in gaps:
        start = gap["candle_index"] + 2
        for candle in candles[start:]:
            if gap["type"] == "bullish":
                if candle["low"] <= gap["bottom"]:
                    gap["status"] = "filled"
                    gap["filled_at"] = candle["time"]
                    break
                if candle["low"] < gap["top"]:
                    gap["status"] = "partially_filled"
            else:
                if candle["high"] >= gap["top"]:
                    gap["status"] = "filled"
                    gap["filled_at"] = candle["time"]
                    break
                if candle["high"] > gap["bottom"]:
                    gap["status"] = "partially_filled"
    for gap in gaps:
        del gap["candle_index"]
    return gaps


def detect_order_blocks(candles: list, displacement_factor: float = 1.5,
                        atr_period: int = 14) -> list:
    """
    Order blocks con heurística de desplazamiento:

        - Vela de desplazamiento = |close - open| > displacement_factor * ATR.
        - OB alcista: la última vela BAJISTA en las 3 anteriores a un
          desplazamiento ALCISTA. Zona = [low, high] de esa vela.
        - OB bajista: simétrico (última vela alcista antes de un
          desplazamiento bajista).

    Estado según el precio posterior:
        fresh      el precio no ha vuelto a la zona
        mitigated  el precio ha entrado en la zona
        broken     una vela CERRÓ más allá del lado opuesto de la zona
    """
    atrs = atr(candles, atr_period)
    blocks = []
    used = set()
    for j in range(len(candles)):
        if atrs[j] is None or atrs[j] <= 0:
            continue
        body = candles[j]["close"] - candles[j]["open"]
        if abs(body) <= displacement_factor * atrs[j]:
            continue
        direction = "bullish" if body > 0 else "bearish"
        # última vela contraria en las 3 anteriores
        for i in range(j - 1, max(j - 4, -1), -1):
            candle_dir = candles[i]["close"] - candles[i]["open"]
            opposite = candle_dir < 0 if direction == "bullish" else candle_dir > 0
            if opposite and i not in used:
                used.add(i)
                blocks.append({
                    "type": direction,
                    "formed_at": candles[i]["time"],
                    "candle_index": i,
                    "displacement_at": candles[j]["time"],
                    "top": candles[i]["high"],
                    "bottom": candles[i]["low"],
                    "status": "fresh",
                })
                break

    for block in blocks:
        start = block["candle_index"] + 2
        for candle in candles[start:]:
            if block["type"] == "bullish":
                if candle["close"] < block["bottom"]:
                    block["status"] = "broken"
                    break
                if candle["low"] <= block["top"]:
                    block["status"] = "mitigated"
            else:
                if candle["close"] > block["top"]:
                    block["status"] = "broken"
                    break
                if candle["high"] >= block["bottom"]:
                    block["status"] = "mitigated"
    for block in blocks:
        del block["candle_index"]
    return blocks


def find_swings(candles: list, strength: int = 2) -> list:
    """
    Puntos de giro (fractales): swing high si su high supera al de las
    `strength` velas a cada lado; swing low simétrico.
    """
    swings = []
    for i in range(strength, len(candles) - strength):
        window = candles[i - strength:i + strength + 1]
        high_i = candles[i]["high"]
        low_i = candles[i]["low"]
        if high_i == max(c["high"] for c in window) and \
           sum(1 for c in window if c["high"] == high_i) == 1:
            swings.append({"type": "high", "time": candles[i]["time"],
                           "price": high_i})
        if low_i == min(c["low"] for c in window) and \
           sum(1 for c in window if c["low"] == low_i) == 1:
            swings.append({"type": "low", "time": candles[i]["time"],
                           "price": low_i})
    swings.sort(key=lambda s: s["time"])
    return swings


def market_structure(candles: list, strength: int = 2) -> dict:
    """
    Estructura a partir de los swings: etiqueta cada swing como HH/LH
    (highs) o HL/LL (lows) frente al swing previo del mismo tipo, y deriva
    una lectura de tendencia de los dos últimos pares.
    """
    swings = find_swings(candles, strength=strength)
    last = {"high": None, "low": None}
    labeled = []
    for swing in swings:
        prev = last[swing["type"]]
        if prev is None:
            label = None
        elif swing["type"] == "high":
            label = "HH" if swing["price"] > prev else "LH"
        else:
            label = "HL" if swing["price"] > prev else "LL"
        last[swing["type"]] = swing["price"]
        labeled.append({**swing, "label": label})

    labels = [s["label"] for s in labeled if s["label"]]
    recent = labels[-4:]
    if recent.count("HH") + recent.count("HL") >= 3:
        trend = "uptrend"
    elif recent.count("LL") + recent.count("LH") >= 3:
        trend = "downtrend"
    else:
        trend = "range"
    return {"swings": labeled, "trend": trend}

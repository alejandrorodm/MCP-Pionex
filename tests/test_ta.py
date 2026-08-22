"""Tests offline del módulo de análisis técnico (sin red)."""

import pytest

from mcp_pionex import ta


def make_candle(t, o, h, l, c):
    return {"time": t, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


# ---------------------------------------------------------------------------
# Indicadores clásicos
# ---------------------------------------------------------------------------

def test_sma_known_values():
    out = ta.sma([1, 2, 3, 4, 5], 3)
    assert out == [None, None, 2.0, 3.0, 4.0]


def test_ema_seed_is_sma_then_recursive():
    out = ta.ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0                      # semilla = SMA(1,2,3)
    assert out[3] == pytest.approx(3.0)       # 4*0.5 + 2*0.5
    assert out[4] == pytest.approx(4.0)


def test_rsi_all_gains_is_100():
    closes = list(range(1, 20))
    out = ta.rsi(closes, 14)
    assert out[-1] == 100.0


def test_rsi_bounded():
    closes = [100 + ((-1) ** i) * (i % 5) for i in range(60)]
    values = [v for v in ta.rsi(closes, 14) if v is not None]
    assert values and all(0.0 <= v <= 100.0 for v in values)


def test_macd_shapes():
    closes = [float(i) + (i % 7) for i in range(80)]
    result = ta.macd(closes)
    assert len(result["line"]) == len(closes)
    assert result["line"][-1] is not None
    assert result["signal"][-1] is not None
    assert result["histogram"][-1] == pytest.approx(
        result["line"][-1] - result["signal"][-1]
    )


def test_atr_positive():
    candles = [make_candle(i, 100, 102, 98, 101) for i in range(30)]
    out = ta.atr(candles, 14)
    assert out[-1] == pytest.approx(4.0)      # rango constante h-l = 4


def test_bollinger_constant_series_collapses():
    closes = [50.0] * 30
    boll = ta.bollinger(closes)
    assert boll["upper"][-1] == boll["middle"][-1] == boll["lower"][-1] == 50.0


def test_parse_klines_sorts_and_floats():
    raw = [
        {"time": "2000", "open": "2", "high": "3", "low": "1", "close": "2.5"},
        {"time": "1000", "open": "1", "high": "2", "low": "0.5", "close": "1.5"},
    ]
    candles = ta.parse_klines(raw)
    assert [c["time"] for c in candles] == [1000, 2000]
    assert candles[0]["close"] == 1.5


# ---------------------------------------------------------------------------
# FVG
# ---------------------------------------------------------------------------

def bullish_gap_candles():
    """Tríada con hueco alcista: high de la 1ª = 102, low de la 3ª = 105."""
    return [
        make_candle(1, 100, 102, 99, 101),
        make_candle(2, 101, 106, 101, 105.5),   # vela de impulso
        make_candle(3, 105.5, 108, 105, 107),
    ]


def test_fvg_bullish_detected_open():
    gaps = ta.detect_fvg(bullish_gap_candles())
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["type"] == "bullish"
    assert gap["bottom"] == 102 and gap["top"] == 105
    assert gap["status"] == "open"
    assert gap["formed_at"] == 2


def test_fvg_filled_when_price_crosses_zone():
    candles = bullish_gap_candles() + [
        make_candle(4, 107, 107, 104, 104.5),   # entra en la zona
        make_candle(5, 104.5, 105, 101, 102),   # la cruza entera
    ]
    gap = ta.detect_fvg(candles)[0]
    assert gap["status"] == "filled"
    assert gap["filled_at"] == 5


def test_fvg_partial_fill():
    candles = bullish_gap_candles() + [
        make_candle(4, 107, 107, 103.5, 106),   # entra pero no llega al bottom
    ]
    assert ta.detect_fvg(candles)[0]["status"] == "partially_filled"


def test_fvg_bearish():
    candles = [
        make_candle(1, 100, 101, 98, 99),
        make_candle(2, 99, 99, 93, 94),
        make_candle(3, 94, 96, 92, 95),         # high 96 < low[0] 98
    ]
    gap = ta.detect_fvg(candles)[0]
    assert gap["type"] == "bearish"
    assert gap["bottom"] == 96 and gap["top"] == 98


def test_fvg_min_gap_filter():
    assert ta.detect_fvg(bullish_gap_candles(), min_gap_pct=5.0) == []


# ---------------------------------------------------------------------------
# Order blocks
# ---------------------------------------------------------------------------

def ob_candles():
    """Serie plana + vela bajista + desplazamiento alcista fuerte."""
    flat = [make_candle(i, 100, 101, 99, 100.5) for i in range(20)]
    bearish = make_candle(20, 100.5, 101, 99.5, 99.8)          # OB candidato
    displacement = make_candle(21, 99.8, 112, 99.8, 111)       # cuerpo >> ATR
    return flat + [bearish, displacement]


def test_order_block_bullish_detected():
    blocks = ta.detect_order_blocks(ob_candles())
    assert any(
        b["type"] == "bullish" and b["formed_at"] == 20 and b["status"] == "fresh"
        for b in blocks
    )


def test_order_block_mitigated_and_broken():
    mitigated = ob_candles() + [make_candle(23, 111, 111, 100.5, 105)]
    block = [b for b in ta.detect_order_blocks(mitigated) if b["formed_at"] == 20][0]
    assert block["status"] == "mitigated"

    broken = ob_candles() + [make_candle(23, 111, 111, 95, 96)]  # cierra bajo el bottom
    block = [b for b in ta.detect_order_blocks(broken) if b["formed_at"] == 20][0]
    assert block["status"] == "broken"


# ---------------------------------------------------------------------------
# Swings y estructura
# ---------------------------------------------------------------------------

def test_find_swings_detects_peak_and_trough():
    highs = [100, 101, 105, 101, 100, 99, 95, 99, 100]
    candles = [make_candle(i, h - 1, h, h - 2, h - 1) for i, h in enumerate(highs)]
    swings = ta.find_swings(candles, strength=2)
    assert {"type": "high", "time": 2, "price": 105} in swings
    assert any(s["type"] == "low" and s["time"] == 6 for s in swings)


def test_market_structure_uptrend():
    # Picos y valles ascendentes: HH y HL consecutivos
    pattern = [100, 105, 100, 103, 110, 103, 106, 115, 106, 109, 120, 109]
    candles = [make_candle(i, p - 1, p, p - 2, p - 1)
               for i, p in enumerate(pattern)]
    result = ta.market_structure(candles, strength=1)
    assert result["trend"] == "uptrend"

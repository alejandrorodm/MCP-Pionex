# Informe de capacidades — Servidor MCP para Pionex (`mcp-pionex`)

**Fecha:** 2026-08-22 · **Versión:** 1.0.0 · **Base:** librería `pionex_py` 1.2.0 · **SDK:** `mcp` ≥ 2.0

## 1. Resumen ejecutivo

`mcp-pionex` convierte la librería `pionex_py` en un servidor **Model Context Protocol** que permite a un asistente de IA (Claude Code, Claude Desktop o cualquier cliente MCP) consultar y operar el exchange Pionex con **38 herramientas** organizadas en 6 grupos. Su rasgo diferencial es una **capa de seguridad anti-alucinación**: ningún dato inventado por el modelo puede llegar a la API, y ninguna operación con dinero se ejecuta sin validación contra datos vivos del exchange más una confirmación en dos fases aprobada por el humano.

Estado verificado: las 38 tools registran correctamente, las herramientas públicas funcionan contra la API real de Pionex, los 11 tests offline de la capa de seguridad pasan, y el flujo completo prepare→confirm se ha probado de extremo a extremo (incluyendo bloqueos por tope de nocional, desviación de precio, token caducado/reutilizado y passthrough literal de errores de la API como `INVALID_APIKEY`).

## 2. Inventario de capacidades

### 2.1 Meta e introspección (2 tools, siempre disponibles)

| Tool | Qué hace |
|---|---|
| `get_server_status` | Versión, credenciales configuradas, qué puertas (trading/bots/earn) están activas, límites vigentes, confirmaciones pendientes, ruta del audit log |
| `get_safety_rules` | Lista completa de las reglas de seguridad activas, con los valores actuales de cada límite |

### 2.2 Datos de mercado (9 tools, públicas, sin API key)

| Tool | Endpoint | Notas |
|---|---|---|
| `list_symbols` | `GET /api/v1/common/symbols` | Nombres reales de pares (SPOT/PERP), con filtro de búsqueda |
| `get_symbol_info` | `GET /api/v1/common/symbols` | Precisiones, mínimos (`minAmount`, `minTradeSize`), estado |
| `get_price` | bookTickers (+fallback tickers) | Mid-price (bid+ask)/2, marcado `computed` |
| `get_ticker_24h` | `GET /api/v1/market/tickers` | OHLCV rodante 24 h, un par o todos |
| `get_book_ticker` | `GET /api/v1/market/bookTickers` | Mejor bid/ask con tamaños |
| `get_depth` | `GET /api/v1/market/depth` | Libro de órdenes, 1–1000 niveles |
| `get_recent_trades` | `GET /api/v1/market/trades` | Últimas operaciones públicas, 10–500 |
| `get_klines` | `GET /api/v1/market/klines` | Velas; intervalos exactos 1M,5M,15M,30M,60M,4H,8H,12H,1D; 1–500 |
| `get_klines_history` | klines paginado | Hasta 5000 velas, orden antiguo→reciente |

### 2.3 Cuenta (8 tools, lectura, requieren API key)

| Tool | Endpoint | Notas |
|---|---|---|
| `get_balances` | `GET /api/v1/account/balances` | free/frozen/total por moneda |
| `get_portfolio` | balances + precios vivos | Valoración completa con pesos, `computed` |
| `get_open_orders` | `GET /api/v1/trade/openOrders` | Órdenes abiertas por par |
| `get_order` | `GET /api/v1/trade/order` | Detalle por orderId |
| `get_order_by_client_id` | `GET /api/v1/trade/orderByClientOrderId` | Detalle por clientOrderId |
| `get_order_history` | `GET /api/v1/trade/allOrders` | Histórico, hasta 200, rango temporal |
| `get_fills` | `GET /api/v1/trade/fills` | Ejecuciones recientes con comisión y rol |
| `get_fills_by_order` | `GET /api/v1/trade/fillsByOrderId` | Precio medio real de una orden |

### 2.4 Trading spot (6 tools, requieren `PIONEX_MCP_TRADING_ENABLED=true`)

| Tool | Fase | Qué hace |
|---|---|---|
| `prepare_order` | 1/2 | Valida orden LIMIT/MARKET contra datos vivos y devuelve token; **no envía nada** |
| `confirm_action` | 2/2 | Ejecuta cualquier acción preparada (órdenes, bots, earn) con su token de un solo uso |
| `prepare_cancel_all_orders` | 1/2 | Cancelación masiva de un par, con recuento de abiertas en el resumen |
| `cancel_order` | directa | Cancela UNA orden identificada (riesgo bajo, sin token) |
| `compute_rebalance_plan` | dry-run | Plan de rebalanceo a pesos objetivo; nunca ejecuta |
| `prepare_rebalance` | 1/2 | Rebalanceo real: replan con datos vivos + tope por orden + token |

Reglas de una orden (idénticas a la API): LIMIT → `price`+`size`; MARKET BUY → `amount` en quote; MARKET SELL → `size` en base. Valores numéricos como strings, tal cual llegan al exchange.

### 2.5 Grid bots (6 tools; escrituras requieren `PIONEX_MCP_BOTS_ENABLED=true`)

| Tool | Qué hace |
|---|---|
| `list_bot_orders` | Lista bots (filtros por estado, par, tipo) |
| `get_spot_grid` | Estado completo de un grid bot |
| `get_grid_ai_strategy` | Parámetros recomendados por la IA de Pionex (top/bottom/row) |
| `check_spot_grid_params` | El **exchange** valida los parámetros, sin crear nada |
| `prepare_create_spot_grid` | Valida local + checkParams del exchange + tope de inversión → token |
| `prepare_cancel_spot_grid` | Cierra un grid (muestra el estado vivo en el resumen) → token |

### 2.6 Earn / Dual Investment (7 tools; escrituras requieren `PIONEX_MCP_EARN_ENABLED=true`)

| Tool | Qué hace |
|---|---|
| `list_dual_symbols` | Pares soportados (ojo: BTC/ETH usan quote `USDXO`) |
| `list_dual_products` | Productos abiertos; tipo `DUAL_BASE` o `DUAL_CURRENCY` |
| `get_dual_prices` | Rendimientos vivos por productId — fuente obligatoria del `profit` |
| `get_dual_index` | Precio índice del subyacente |
| `get_dual_balances` | Posiciones dual de la cuenta |
| `prepare_dual_invest` | Suscripción con tope de nocional → token |
| `prepare_dual_revoke` | Revocación de una inversión no liquidada → token |

## 3. Sistema anti-alucinación

| # | Regla | Mecanismo | Qué evita |
|---|---|---|---|
| 1 | Vocabularios cerrados | Whitelists hardcodeadas (side, type, interval, market, grid, dual); el error devuelve la lista válida completa | Que el modelo invente `"2H"` o `"STOP_LOSS"` |
| 2 | Símbolos verificados en vivo | Contra `GET /common/symbols` (caché 10 min) + sugerencias «¿quisiste decir BTC_USDT?» | Pares inexistentes o mal formateados (`BTC/USDT`, `BTCUSDT`) |
| 3 | Commit en dos fases | Token = hash SHA-256 de acción+params + nonce; un solo uso; TTL 120 s; en la confirmación se ejecutan los **params almacenados en el servidor** | Que el modelo ejecute algo distinto de lo validado y mostrado al usuario |
| 4 | Tope de nocional | `PIONEX_MCP_MAX_ORDER_NOTIONAL` (100 por defecto) sobre órdenes, rebalanceos, grids e inversiones | Órdenes desproporcionadas por error de magnitud |
| 5 | Guarda de desviación de precio | Precio LIMIT a más del X% (10% por defecto) del mid-price vivo → rechazo | Precios recordados de datos de entrenamiento obsoletos |
| 6 | Solo lectura por defecto | Trading/bots/earn OFF hasta que el **operador** exporte la variable; imposible de cambiar desde el chat | Operativa no autorizada |
| 7 | Whitelist de símbolos | `PIONEX_MCP_SYMBOL_WHITELIST` opcional | Operar fuera del universo autorizado |
| 8 | Procedencia obligatoria | Envelope `{ok, source, fetched_at, computed, data}`; derivados marcados `computed` + `note` | Confundir hechos del exchange con aritmética del servidor |
| 9 | Errores verbatim | `code` y `message` originales de la API + instrucción de no especular | Explicaciones inventadas de errores |
| 10 | Auditoría | JSONL en `~/.mcp_pionex/audit.jsonl` con cada prepare/execute | Operaciones sin rastro |

Además, las *instructions* del servidor (que el cliente MCP inyecta en el contexto del modelo) ordenan explícitamente: nunca citar precios/balances sin llamar a una tool en ese mismo turno, solo reportar campos presentes en `data`, y nunca fabricar ni reutilizar tokens.

## 4. Cómo utilizarlo

### 4.1 Instalación y registro

```bash
cd /home/zoiyo/repos/mcp_pionex_py
uv sync

# Claude Code:
claude mcp add pionex \
  --env PIONEX_API_KEY=... --env PIONEX_API_SECRET=... \
  -- uv --directory /home/zoiyo/repos/mcp_pionex_py run mcp-pionex
```

Para habilitar operativa real añade en el entorno del servidor (nunca en el chat): `PIONEX_MCP_TRADING_ENABLED=true` (y/o `_BOTS_`, `_EARN_`), ajustando `PIONEX_MCP_MAX_ORDER_NOTIONAL` a tu tolerancia.

### 4.2 Flujos de ejemplo

**Consulta de mercado (sin credenciales):**
> «¿A cuánto está DOGE y cómo fue su día?» → `get_price("DOGE_USDT")` + `get_ticker_24h("DOGE_USDT")` — el modelo responde solo con los valores devueltos.

**Compra con confirmación:**
1. Usuario: «compra 20 USDT de ETH a mercado».
2. `prepare_order(symbol="ETH_USDT", side="BUY", order_type="MARKET", amount="20")` → resumen + token `a1b2c3d4e5f6-9x8y`.
3. El asistente muestra el resumen; el usuario dice «confirmo».
4. `confirm_action("a1b2c3d4e5f6-9x8y")` → orden real; respuesta con `orderId` del exchange.

**Rebalanceo de cartera:**
1. `get_portfolio()` → pesos actuales.
2. `compute_rebalance_plan('{"BTC":0.5,"ETH":0.3,"USDT":0.2}')` → plan dry-run redondeado a la precisión del exchange.
3. Si convence: `prepare_rebalance(...)` → token → `confirm_action`.

**Grid bot con parámetros del exchange (no inventados):**
1. `get_grid_ai_strategy(base="BTC", quote="USDT")` → top/bottom/row recomendados por Pionex.
2. `check_spot_grid_params(...)` → veredicto del exchange.
3. `prepare_create_spot_grid(...)` → token → `confirm_action`.

### 4.3 Qué esperar cuando algo se bloquea

Cada guardia responde con el motivo exacto y la variable de entorno que lo controla. Ejemplos reales de las pruebas:

- `Symbol 'BTC/USDT' does not exist on Pionex (SPOT). Did you mean: BTC_USDT?`
- `prepare_order: notional 500.00 exceeds the operator-configured cap of 100.00 (PIONEX_MCP_MAX_ORDER_NOTIONAL).`
- `LIMIT price 1000.0 deviates 98.71% from the live mid-price 77349.36 … the operator cap is 10.0%.`
- `Unknown or already-used confirmation token … Tokens are single-use.`

## 5. Límites conocidos

- **Sin WebSocket**: los streams de `pionex_py` (PublicStream/PrivateStream) no se exponen — MCP es petición/respuesta; usa `get_klines`/`get_price` para instantáneas.
- **Futures grid y smart copy**: la librería los soporta; el MCP expone de momento solo lectura genérica (`list_bot_orders`) y ciclo completo para spot grid. Ampliar es añadir un `prepare_*` + `@executor` siguiendo el patrón.
- **`cancel_order` es directa** (sin token) por decisión de diseño: cancelar una orden identificada es de bajo riesgo.
- **Tokens en memoria**: las confirmaciones pendientes viven en el proceso; reiniciar el servidor las invalida (comportamiento deseado).
- La API de Pionex limita klines a 500/petición (paginamos hasta 5000) e histórico de órdenes a 200.

## 6. Verificación realizada

| Prueba | Resultado |
|---|---|
| Registro de tools | 38/38 |
| Tests offline capa seguridad (`pytest tests/`) | 11/11 pasan |
| API pública real (precio, depth, ticker, klines, símbolos) | OK, valores vivos |
| Símbolo inexistente / intervalo inválido / sin credenciales | Bloqueados con mensaje correctivo |
| Tope de nocional y desviación de precio | Bloquean con datos vivos |
| Flujo prepare→confirm, token único, caducidad, reuso | OK |
| Error de API verbatim (`INVALID_APIKEY`) | Passthrough intacto |
| Audit log JSONL | Escribe cada prepare/execute |

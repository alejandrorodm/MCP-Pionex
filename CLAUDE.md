# CLAUDE.md — mcp-pionex

Servidor MCP para el exchange Pionex, construido sobre la librería `pionex_py`
(dependencia desde PyPI; para desarrollar contra un checkout local en
`../pionex_py`, descomenta el override `[tool.uv.sources]` del pyproject).
Expone mercado, cuenta, trading spot, grid bots y Dual Investment como
herramientas MCP con una capa estricta anti-alucinación.

Repo: <https://github.com/alejandrorodm/MCP-Pionex>

## Comandos

```bash
uv sync                          # instalar (crea .venv)
uv run mcp-pionex                # arrancar el servidor (stdio)
uv run --with pytest pytest tests/ -q   # tests offline de la capa de seguridad
```

Verificación rápida de registro de tools:

```bash
uv run python -c "
from mcp_pionex.server import mcp; import asyncio
print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

## Arquitectura

```
src/mcp_pionex/
├── server.py      # MCPServer (SDK mcp>=2.0), instructions anti-alucinación,
│                  # tools meta (get_server_status, get_safety_rules) y registro
│                  # de los grupos de tools
├── config.py      # Settings inmutables leídos del entorno; defaults conservadores
├── safety.py      # LA capa importante: vocabularios cerrados, verificación de
│                  # símbolos en vivo, two-phase commit, límites, envelopes,
│                  # errores verbatim, auditoría
├── client.py      # singletons perezosos de los clientes pionex_py
│                  # (con fix del doble-slash en base_url — ver Gotchas)
├── actions.py     # registro EXECUTORS: nombre de acción -> función ejecutora
├── ta.py          # análisis técnico puro (EMA/RSI/MACD/ATR/Bollinger, FVG,
│                  # order blocks, swings) — determinista, sin red, testeado
└── tools/
    ├── market.py   # público, sin credenciales
    ├── analysis.py # análisis técnico sobre klines vivas (todo computed:true)
    ├── account.py  # lectura, requiere credenciales
    ├── trading.py  # dos fases, requiere PIONEX_MCP_TRADING_ENABLED
    ├── bots.py     # dos fases, requiere PIONEX_MCP_BOTS_ENABLED
    └── earn.py     # dos fases, requiere PIONEX_MCP_EARN_ENABLED
```

### Patrón de cada tool

Cada tool sigue el mismo esqueleto:

```python
@mcp.tool()
@guarded("GET /api/v1/...")          # fuente que irá en el envelope
def tool_name(...) -> dict:
    require_credentials()            # o require_trading()/require_bots()/require_earn()
    validate_enum(...)               # vocabularios cerrados
    verify_symbol(symbol)            # existencia en vivo + whitelist
    response = xxx_client().método(...)
    return response["data"]          # guarded lo envuelve en el envelope
```

`@guarded(source)` convierte el retorno en un *envelope* de procedencia
(`{ok, source, fetched_at, computed, data}`) y cualquier excepción en un
*error envelope* con código/mensaje literales. Si la tool ya devuelve un
`str`, se asume que ya es un envelope (p. ej. cuando necesita `computed=True`
o una `note`).

### Two-phase commit (crítico — no romper)

Toda acción que cambia estado sigue: `prepare_*` → `confirm_action(token)`.

- `safety.prepare_action(action, params, summary)` guarda los params
  VALIDADOS bajo un token `sha256(action+params)[:12] + "-" + nonce`, con TTL
  (`PIONEX_MCP_CONFIRMATION_TTL`, 120 s por defecto) y un solo uso.
- `confirm_action` recupera la entrada con `safety.take_pending(token)` y
  despacha al ejecutor registrado en `actions.EXECUTORS` para ese nombre de
  acción. **Los params ejecutados son los almacenados**; nada de lo que se
  pase en la confirmación puede alterarlos.
- Para añadir una acción nueva: registrar el ejecutor con
  `@executor("nombre")` en el módulo de tools correspondiente y crear su
  `prepare_*` que valide TODO antes de llamar a `prepare_action`.

### Puertas y límites (solo operador)

Todo vive en `config.py` y se lee del entorno al arrancar. La conversación
con el modelo jamás debe poder cambiarlos — no añadas tools que modifiquen
`SETTINGS`.

| Variable | Defecto | Efecto |
|---|---|---|
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | vacío | credenciales |
| `PIONEX_MCP_TRADING_ENABLED` | false | habilita trading spot |
| `PIONEX_MCP_BOTS_ENABLED` | false | habilita crear/cerrar bots |
| `PIONEX_MCP_EARN_ENABLED` | false | habilita invertir/revocar dual |
| `PIONEX_MCP_MAX_ORDER_NOTIONAL` | 100 | tope quote por acción |
| `PIONEX_MCP_MAX_PRICE_DEVIATION_PCT` | 10 | desviación máx. precio LIMIT |
| `PIONEX_MCP_SYMBOL_WHITELIST` | vacío | restringe pares operables |
| `PIONEX_MCP_CONFIRMATION_TTL` | 120 | caducidad de tokens |
| `PIONEX_MCP_AUDIT_LOG` | `~/.mcp_pionex/audit.jsonl` | log JSONL de prepare/execute |

## Catálogo de tools (43)

**Meta (2):** `get_server_status`, `get_safety_rules`.

**Mercado — público, sin credenciales (9):** `list_symbols`,
`get_symbol_info`, `get_price` (mid-price computado, marcado `computed`),
`get_ticker_24h`, `get_book_ticker`, `get_depth`, `get_recent_trades`,
`get_klines`, `get_klines_history` (paginado hasta 5000 velas).

**Análisis técnico — público, todo `computed` (5):** `get_emas`,
`get_indicators` (RSI 14, MACD 12-26-9, ATR 14, Bollinger 20-2, SMA/EMA
20/50/200), `detect_fvg` (Fair Value Gaps, definición 3-velas, con estado
open/partially_filled/filled), `detect_order_blocks` (heurística de
desplazamiento cuerpo > factor×ATR, estado fresh/mitigated/broken),
`get_market_structure` (swings fractales HH/LH/HL/LL + tendencia). Cálculo
puro en `ta.py` (testeado offline en `tests/test_ta.py`); las tools en
`tools/analysis.py` solo obtienen klines vivas y envuelven con `computed:
true` + nota con la definición exacta.

**Cuenta — lectura con credenciales (8):** `get_balances`, `get_portfolio`
(valorado en vivo, `computed`), `get_open_orders`, `get_order`,
`get_order_by_client_id`, `get_order_history`, `get_fills`,
`get_fills_by_order`.

**Trading — dos fases, gate de trading (6):** `prepare_order`,
`prepare_cancel_all_orders`, `cancel_order` (directo: bajo riesgo),
`compute_rebalance_plan` (siempre dry-run), `prepare_rebalance`,
`confirm_action` (ejecutor común de TODAS las acciones preparadas, también
bots y earn).

**Bots — gate de bots para escrituras (6):** `list_bot_orders`,
`get_spot_grid`, `get_grid_ai_strategy`, `check_spot_grid_params` (validación
del exchange, sin crear nada), `prepare_create_spot_grid`,
`prepare_cancel_spot_grid`.

**Earn / Dual Investment — gate de earn para escrituras (7):**
`list_dual_symbols`, `list_dual_products`, `get_dual_prices`,
`get_dual_index`, `get_dual_balances`, `prepare_dual_invest`,
`prepare_dual_revoke`.

## Reglas anti-alucinación (diseño)

1. **Vocabularios cerrados** en `safety.py`: `VALID_SIDES`,
   `VALID_ORDER_TYPES`, `VALID_MARKET_TYPES` (SPOT/PERP),
   `VALID_KLINE_INTERVALS` (1M…1D), `VALID_GRID_TYPES`, `VALID_TRENDS`,
   `VALID_DUAL_TYPES`. Los mensajes de error incluyen la lista válida
   completa para que el modelo se autocorrija.
2. **`verify_symbol`**: todo símbolo se comprueba contra
   `GET /api/v1/common/symbols` (caché 10 min) y contra la whitelist del
   operador; ofrece «¿quisiste decir…?» normalizando separadores.
3. **Two-phase commit** con token ligado a parámetros (ver arriba).
4. **Límites numéricos** server-side (`check_notional_cap`,
   `check_price_deviation` contra mid-price vivo).
5. **Envelopes de procedencia** en toda respuesta; los valores derivados
   llevan `computed: true` y una `note` explicando la derivación.
6. **Errores verbatim** (`error_envelope` conserva `code` y `message` de la
   API, p. ej. `INVALID_APIKEY`).
7. **Instructions del servidor** (en `server.py`) ordenan al modelo: nunca
   citar precios de memoria, solo reportar campos presentes en `data`,
   nunca fabricar tokens.
8. **Auditoría JSONL** de cada prepare/execute.

## Gotchas

- **SDK `mcp>=2.0`**: la clase es `mcp.server.mcpserver.MCPServer` (el viejo
  `mcp.server.fastmcp.FastMCP` ya no existe). La API de decoradores es igual.
  `call_tool` devuelve `CallToolResult` con `.content[0].text`. En el lado
  cliente los atributos son snake_case (`init.server_info`, no `serverInfo`).
- **Doble slash**: `pionex_py` define `base_url = 'https://api.pionex.com/'`
  y los paths empiezan por `/`; Pionex devuelve `404 page not found` con
  `//api/...`. `client.py::_normalized` recorta la barra final — cualquier
  cliente nuevo debe pasar por ahí.
- Los decoradores sobre tools deben usar `functools.wraps` (el SDK
  introspecciona la firma con pydantic; una firma `*args, **kwargs` rompe el
  registro).
- El casing de la API de bots es inconsistente a propósito (`buOrderId` en
  grid, `bu_order_id` en smart copy) — `pionex_py` ya lo respeta; no
  «normalices».
- Dual Investment: pares BTC/ETH usan quote `USDXO`, el resto `USDT`.
- Los tests en `tests/` son offline (solo `safety.py`); las smoke-tests de
  mercado golpean la API pública real.

## Documentos

- `README.md` — instalación, configuración y registro en Claude Code.
- `docs/GUIA.md` — guía completa: integraciones (Claude, LM Studio, Ollama),
  posturas de seguridad, troubleshooting, extensión.
- `docs/INFORME.md` — informe completo de capacidades y manual de uso.
- `examples/ollama_bridge.py` — puente agéntico Ollama↔MCP de referencia.
- `.github/workflows/ci.yml` — CI: tests + comprobación de 43 tools.
- API oficial: <https://pionex-doc.gitbook.io/apidocs/> y
  <https://github.com/pionex-official/pionex-open-api>.

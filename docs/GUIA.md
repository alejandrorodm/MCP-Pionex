# Guía completa de MCP-Pionex

Servidor **Model Context Protocol** para operar el exchange **Pionex** desde asistentes de IA — Claude Code, Claude Desktop o cualquier LLM local con soporte de tool-calling — con guardas estrictas que impiden que el modelo actúe sobre datos inventados.

> Documentos hermanos: [`README.md`](../README.md) (arranque rápido) · [`INFORME.md`](INFORME.md) (informe de capacidades y verificación) · [`../CLAUDE.md`](../CLAUDE.md) (guía interna para agentes que desarrollen el proyecto).

---

## 1. Qué es y qué resuelve

Un LLM conectado a un exchange plantea dos riesgos concretos:

1. **Alucinación de datos** — precios de memoria (siempre obsoletos), pares que no existen (`BTC/USDT`, `BTCUSDT`), parámetros inventados (`interval="2H"`).
2. **Ejecución no supervisada** — que una orden real se envíe sin que un humano haya visto y aprobado exactamente lo que se va a ejecutar.

MCP-Pionex resuelve ambos **en el servidor**, no confiando en el modelo:

- Todo dato variable se obtiene de la API en el momento; todo parámetro se valida contra vocabularios cerrados y contra el estado vivo del exchange.
- Toda operación con dinero exige dos fases: `prepare_*` (valida y devuelve un token ligado a los parámetros) → aprobación humana → `confirm_action(token)`. El token es de un solo uso, caduca, y en la confirmación se ejecutan los parámetros **almacenados en el servidor** — el modelo no puede cambiarlos.
- Los límites (modo solo-lectura, tope de nocional, desviación de precio, whitelist de pares) los fija el operador por variables de entorno y **no pueden modificarse desde la conversación**.

## 2. Requisitos

| Componente | Versión |
|---|---|
| Python | ≥ 3.11 |
| [uv](https://docs.astral.sh/uv/) | recomendado (o pip) |
| `pionex_py` | ≥ 1.2.0 (se instala solo, desde PyPI) |
| SDK `mcp` | ≥ 2.0 (se instala solo) |
| API key de Pionex | solo para cuenta/trading; el mercado es público |

Crea la API key en Pionex (app → API Management) con los **permisos mínimos** que necesites: para consultar basta *Read*; añade *Trade* solo si vas a habilitar trading. Restringe la key por IP si Pionex te lo permite.

## 3. Instalación

```bash
git clone https://github.com/alejandrorodm/MCP-Pionex
cd MCP-Pionex
uv sync
uv run mcp-pionex        # arranca por stdio; Ctrl+C para salir
```

Verificación rápida (sin credenciales — el mercado es público):

```bash
uv run python -c "
from mcp_pionex.server import mcp; import asyncio
print(len(asyncio.run(mcp.list_tools())), 'tools')"
```

## 4. Configuración

Todo por variables de entorno (plantilla en [`.env.example`](../.env.example)):

| Variable | Defecto | Descripción |
|---|---|---|
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | — | Credenciales. Solo en el entorno del servidor, **nunca en el chat** |
| `PIONEX_MCP_TRADING_ENABLED` | `false` | Habilita órdenes spot y rebalanceo |
| `PIONEX_MCP_BOTS_ENABLED` | `false` | Habilita crear/cerrar grid bots |
| `PIONEX_MCP_EARN_ENABLED` | `false` | Habilita invertir/revocar Dual Investment |
| `PIONEX_MCP_MAX_ORDER_NOTIONAL` | `100` | Tope (en moneda quote) por orden/inversión/tramo de rebalanceo |
| `PIONEX_MCP_MAX_PRICE_DEVIATION_PCT` | `10` | Desviación máxima de un precio LIMIT frente al mid-price vivo |
| `PIONEX_MCP_SYMBOL_WHITELIST` | vacío | `BTC_USDT,ETH_USDT` para restringir el universo operable |
| `PIONEX_MCP_CONFIRMATION_TTL` | `120` | Segundos de validez de un token de confirmación |
| `PIONEX_MCP_AUDIT_LOG` | `~/.mcp_pionex/audit.jsonl` | Registro JSONL de cada prepare/execute |

### Posturas recomendadas

| Postura | Variables | Para qué |
|---|---|---|
| **Consulta** (defecto) | solo las credenciales (opcionales) | Precios, análisis, cartera, histórico. Cero riesgo |
| **Trading acotado** | `TRADING_ENABLED=true` + `MAX_ORDER_NOTIONAL=50` + `SYMBOL_WHITELIST=BTC_USDT,ETH_USDT` | Operar con importes pequeños en pares conocidos |
| **Completa** | las tres puertas a `true`, tope a tu tolerancia | Gestión integral (órdenes + bots + earn), siempre con confirmación en dos fases |

## 5. Integración con Claude

### 5.1 Claude Code (CLI)

```bash
claude mcp add pionex \
  --env PIONEX_API_KEY=tu_key \
  --env PIONEX_API_SECRET=tu_secret \
  --env PIONEX_MCP_TRADING_ENABLED=false \
  -- uv --directory /ruta/a/MCP-Pionex run mcp-pionex
```

Comprueba con `claude mcp list` y, dentro de una sesión, pide: *«¿cuál es el estado del servidor de Pionex?»* — debe llamar a `get_server_status`.

### 5.2 Proyecto (`.mcp.json`) o Claude Desktop (`claude_desktop_config.json`)

Mismo formato en ambos:

```json
{
  "mcpServers": {
    "pionex": {
      "command": "uv",
      "args": ["--directory", "/ruta/a/MCP-Pionex", "run", "mcp-pionex"],
      "env": {
        "PIONEX_API_KEY": "tu_key",
        "PIONEX_API_SECRET": "tu_secret",
        "PIONEX_MCP_TRADING_ENABLED": "false",
        "PIONEX_MCP_MAX_ORDER_NOTIONAL": "100"
      }
    }
  }
}
```

- Claude Desktop: **Settings → Developer → Edit Config**, pega el bloque y reinicia la app.
- Claude Code por proyecto: guarda `.mcp.json` en la raíz del repo donde quieras tenerlo disponible (sin credenciales si el repo es compartido — usa variables del sistema).

El servidor publica sus *instructions* anti-alucinación por el protocolo MCP, así que Claude las recibe automáticamente al conectar: nunca citar precios de memoria, solo reportar campos presentes en `data`, nunca fabricar tokens.

### 5.3 Ejemplo de sesión

```text
Tú:     ¿a cuánto está el BTC y cómo va mi cartera?
Claude: [get_price("BTC_USDT")] [get_portfolio()]
        BTC está a 77.349,35 USDT. Tu cartera vale 1.240 USDT: 62% BTC, 25% ETH…

Tú:     compra 20 USDT de ETH a mercado
Claude: [prepare_order(symbol="ETH_USDT", side="BUY", order_type="MARKET", amount="20")]
        Resumen: BUY MARKET ETH_USDT, gastar 20 USDT (nocional ≈ 20).
        ¿Confirmas? (token c2cea1afedaa-8833064d, caduca en 120 s)
Tú:     confirmo
Claude: [confirm_action("c2cea1afedaa-8833064d")]
        Orden ejecutada. orderId 123456789.
```

## 6. Integración con un LLM local

Cualquier runtime local que hable MCP o tenga tool-calling sirve. Tres vías, de menos a más manual:

### 6.1 LM Studio (soporte MCP nativo)

LM Studio (≥ 0.3.17) acepta el mismo formato `mcpServers`. En **Program → Install → Edit mcp.json**:

```json
{
  "mcpServers": {
    "pionex": {
      "command": "uv",
      "args": ["--directory", "/ruta/a/MCP-Pionex", "run", "mcp-pionex"],
      "env": { "PIONEX_API_KEY": "tu_key", "PIONEX_API_SECRET": "tu_secret" }
    }
  }
}
```

Carga un modelo con tool-calling (Qwen3, Llama 3.1+, Mistral…) y las 43 tools aparecen en el chat. LM Studio pide confirmación por cada llamada a tool — una capa más sobre el prepare/confirm del servidor.

### 6.2 Ollama + mcphost

[`mcphost`](https://github.com/mark3labs/mcphost) es un host MCP de terminal para modelos de Ollama:

```bash
ollama pull qwen3
mcphost -m ollama:qwen3 --config /ruta/a/mcp.json   # mismo formato mcpServers
```

### 6.3 Puente Python incluido (Ollama directo)

El repo trae [`examples/ollama_bridge.py`](../examples/ollama_bridge.py): arranca el servidor por stdio con el SDK cliente de `mcp`, convierte las tools al formato de Ollama y ejecuta el bucle agéntico completo. Las *instructions* anti-alucinación del servidor se inyectan como system prompt del modelo local.

```bash
ollama pull qwen3
uv run examples/ollama_bridge.py "¿a cuánto está el BTC?"
OLLAMA_MODEL=llama3.1 uv run examples/ollama_bridge.py "lista los pares con DOGE"
```

Es también la referencia si quieres integrar cualquier otro runtime (llama.cpp, vLLM, LocalAI): basta replicar la conversión `to_ollama_tools` y el bucle de mensajes.

> **Importante con modelos locales**: los modelos pequeños alucinan más, no menos. Las guardas del servidor son idénticas (un símbolo inventado se rechaza igual), pero mantén `PIONEX_MCP_TRADING_ENABLED=false` con modelos locales salvo que supervises cada confirmación.

## 7. Catálogo de herramientas (43)

| Grupo | Tools | Acceso |
|---|---|---|
| Meta | `get_server_status`, `get_safety_rules` | siempre |
| Mercado (9) | `list_symbols`, `get_symbol_info`, `get_price`, `get_ticker_24h`, `get_book_ticker`, `get_depth`, `get_recent_trades`, `get_klines`, `get_klines_history` | público |
| Análisis técnico (5) | `get_emas`, `get_indicators`, `detect_fvg`, `detect_order_blocks`, `get_market_structure` | público (todo `computed`) |
| Cuenta (8) | `get_balances`, `get_portfolio`, `get_open_orders`, `get_order`, `get_order_by_client_id`, `get_order_history`, `get_fills`, `get_fills_by_order` | API key |
| Trading (6) | `prepare_order`, `confirm_action`, `prepare_cancel_all_orders`, `cancel_order`, `compute_rebalance_plan`, `prepare_rebalance` | gate trading |
| Bots (6) | `list_bot_orders`, `get_spot_grid`, `get_grid_ai_strategy`, `check_spot_grid_params`, `prepare_create_spot_grid`, `prepare_cancel_spot_grid` | lectura: API key · escritura: gate bots |
| Earn (7) | `list_dual_symbols`, `list_dual_products`, `get_dual_prices`, `get_dual_index`, `get_dual_balances`, `prepare_dual_invest`, `prepare_dual_revoke` | lectura: pública/API key · escritura: gate earn |

Detalle campo a campo en [`INFORME.md`](INFORME.md).

## 8. Flujos de trabajo

**Análisis de mercado** — `get_ticker_24h` → `get_klines(interval="1D")` → `get_depth`. Todo público, sin riesgo.

**Análisis técnico / SMC** — `get_indicators` (RSI, MACD, ATR, Bollinger) + `get_emas("20,50,200")` para el contexto; `get_market_structure` para la tendencia (HH/HL vs LH/LL); `detect_fvg(only_open=True)` y `detect_order_blocks` para zonas de interés. Todo se calcula sobre velas vivas y viene marcado `computed: true` con la definición exacta en `note` — pide al asistente que cite las zonas con sus timestamps. Ejemplo: *«analiza BTC_USDT en 4H: tendencia, FVGs abiertos y order blocks sin mitigar cerca del precio»*.

**Compra/venta** — `prepare_order` → mostrar resumen → aprobación humana → `confirm_action`. Reglas de la API: LIMIT lleva `price`+`size`; MARKET BUY lleva `amount` (quote); MARKET SELL lleva `size` (base). Números como strings.

**Rebalanceo de cartera** — `get_portfolio` → `compute_rebalance_plan('{"BTC":0.5,"ETH":0.3,"USDT":0.2}')` (dry-run, redondeado a la precisión del exchange, descarta lo que no llega al mínimo) → `prepare_rebalance` → `confirm_action`.

**Grid bot** — `get_grid_ai_strategy` (parámetros recomendados por Pionex, no inventados) → `check_spot_grid_params` (veredicto del exchange) → `prepare_create_spot_grid` → `confirm_action`.

**Dual Investment** — `list_dual_products` → `get_dual_prices` (de aquí sale el `profit`, obligatorio que sea el vivo) → `prepare_dual_invest` → `confirm_action`.

## 9. Seguridad operacional

- **API key de mínimo privilegio**: sin permiso *Trade* si solo consultas; sin *Withdraw* nunca (este servidor no expone retiradas, pero la key tampoco debería poder).
- **Credenciales solo en el entorno** del proceso servidor (config MCP o gestor de secretos). Si una key se pega por error en un chat, revócala.
- **Empieza en solo-lectura** y sube la postura gradualmente. El tope de nocional es tu red de seguridad real: ponlo en lo que estés dispuesto a perder por una orden equivocada.
- **Revisa el audit log** (`~/.mcp_pionex/audit.jsonl`): cada prepare y execute queda registrado con timestamp UTC, parámetros y resultado.
- Reiniciar el servidor invalida los tokens pendientes — es intencional.

## 10. Solución de problemas

| Síntoma | Causa y solución |
|---|---|
| `Trading is DISABLED (read-only mode)` | Falta `PIONEX_MCP_TRADING_ENABLED=true` en el **entorno del servidor** (no basta decírselo al modelo) |
| `This tool needs a Pionex API key` | Faltan `PIONEX_API_KEY`/`PIONEX_API_SECRET` en la config MCP |
| `INVALID_APIKEY` | Key/secret incorrectos o key sin el permiso necesario — error literal de Pionex |
| `Symbol 'X' does not exist` | Formato correcto: `BASE_QUOTE` (`BTC_USDT`). Usa `list_symbols` |
| `notional … exceeds the operator-configured cap` | Sube `PIONEX_MCP_MAX_ORDER_NOTIONAL` (decisión del operador) o reduce la orden |
| `LIMIT price … deviates …%` | El precio está lejos del mercado vivo; consulta `get_price` y ajusta, o sube `PIONEX_MCP_MAX_PRICE_DEVIATION_PCT` |
| `Confirmation token … expired` | Pasaron más de `PIONEX_MCP_CONFIRMATION_TTL` s; vuelve a preparar |
| `404 page not found` en un fork | La `base_url` de `pionex_py` acaba en `/` y los paths empiezan por `/`; `client.py::_normalized` lo corrige — no lo elimines |
| El cliente MCP no ve el servidor | Prueba a mano `uv --directory /ruta run mcp-pionex`; revisa rutas absolutas en la config |

## 11. Desarrollo y extensión

```bash
uv run --with pytest pytest tests/ -q     # 11 tests offline de la capa de seguridad
```

CI en GitHub Actions ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)): tests + comprobación de que las 43 tools registran, en Python 3.11 y 3.12.

**Añadir una acción de escritura nueva** (p. ej. futures grid):

1. En el módulo de tools correspondiente, registra el ejecutor:
   ```python
   @executor("create_futures_grid")
   def _execute(params): ...
   ```
2. Crea `prepare_create_futures_grid(...)` que valide TODO (enums, símbolo vivo, topes) y termine en `safety.prepare_action("create_futures_grid", params, summary)`.
3. `confirm_action` la despacha automáticamente. Añade tests de la validación en `tests/`.

**Añadir una lectura nueva**: función con `@mcp.tool()` + `@guarded("GET /endpoint")`, validar entradas, devolver `response["data"]`.

Convenciones a respetar: decoradores con `functools.wraps` (el SDK introspecciona firmas), casing de la API de bots tal cual (`buOrderId` vs `bu_order_id`), y ningún tool que mute `SETTINGS`.

# MCP-Pionex

[![CI](https://github.com/alejandrorodm/MCP-Pionex/actions/workflows/ci.yml/badge.svg)](https://github.com/alejandrorodm/MCP-Pionex/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Servidor **MCP (Model Context Protocol)** para el exchange **Pionex**, construido sobre la librería [`pionex_py`](https://github.com/alejandrorodm/pionex_py). Expone datos de mercado, cuenta, trading spot, grid bots y Dual Investment como herramientas MCP, con una **capa estricta de seguridad anti-alucinación**: la IA no puede inventar símbolos, precios, parámetros ni ejecutar nada sin validación en vivo y confirmación en dos fases.

Funciona con **Claude Code / Claude Desktop** y con **LLMs locales** (LM Studio, Ollama vía `mcphost` o el [puente incluido](examples/ollama_bridge.py)). Guía completa en [`docs/GUIA.md`](docs/GUIA.md).

## Características

- **43 herramientas** en 7 grupos: meta, mercado (público), análisis técnico (EMAs, RSI, MACD, FVG, order blocks, estructura), cuenta, trading, bots, earn.
- **Solo-lectura por defecto** — el trading, los bots y earn están desactivados hasta que el operador los habilita por variable de entorno.
- **Commit en dos fases** — toda acción que cambia estado (`prepare_*` → `confirm_action`) requiere un token de un solo uso, ligado criptográficamente a los parámetros validados y con caducidad.
- **Verificación de símbolos en vivo** — un par que no existe en Pionex jamás llega a la API.
- **Límites duros** — tope de nocional por orden, desviación máxima de precio límite frente al precio vivo, whitelist opcional de símbolos.
- **Sobres de procedencia** — cada respuesta lleva el endpoint de origen, timestamp UTC y marca `computed` para valores derivados.
- **Errores literales** — los errores de la API de Pionex se devuelven con su código y mensaje originales, nunca parafraseados.
- **Registro de auditoría** — cada prepare/confirm/cancel queda en un JSONL local.

## Requisitos

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (recomendado) o pip
- Una API key de Pionex (solo para herramientas de cuenta/trading; los datos de mercado no la necesitan)

`pionex_py` y el SDK `mcp` se instalan automáticamente desde PyPI.

## Instalación

```bash
git clone https://github.com/alejandrorodm/MCP-Pionex
cd MCP-Pionex
uv sync
```

## Configuración

Todo se controla por variables de entorno (ver `.env.example`):

| Variable | Defecto | Descripción |
|---|---|---|
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | — | Credenciales de la API de Pionex |
| `PIONEX_MCP_TRADING_ENABLED` | `false` | Habilita órdenes spot (prepare/confirm) |
| `PIONEX_MCP_BOTS_ENABLED` | `false` | Habilita crear/cerrar grid bots |
| `PIONEX_MCP_EARN_ENABLED` | `false` | Habilita invertir/revocar Dual Investment |
| `PIONEX_MCP_MAX_ORDER_NOTIONAL` | `100` | Tope de nocional (moneda quote) por acción |
| `PIONEX_MCP_MAX_PRICE_DEVIATION_PCT` | `10` | Desviación máx. de un precio LIMIT vs precio vivo |
| `PIONEX_MCP_SYMBOL_WHITELIST` | vacío | Lista `BTC_USDT,ETH_USDT` para restringir pares |
| `PIONEX_MCP_CONFIRMATION_TTL` | `120` | Segundos de validez de un token de confirmación |
| `PIONEX_MCP_AUDIT_LOG` | `~/.mcp_pionex/audit.jsonl` | Ruta del log de auditoría |

Los límites los fija el **operador humano**: la conversación con la IA no puede subirlos ni desactivarlos.

## Registro en Claude Code

```bash
claude mcp add pionex \
  --env PIONEX_API_KEY=tu_key \
  --env PIONEX_API_SECRET=tu_secret \
  -- uv --directory /home/zoiyo/repos/mcp_pionex_py run mcp-pionex
```

O en `.mcp.json` / `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pionex": {
      "command": "uv",
      "args": ["--directory", "/home/zoiyo/repos/mcp_pionex_py", "run", "mcp-pionex"],
      "env": {
        "PIONEX_API_KEY": "tu_key",
        "PIONEX_API_SECRET": "tu_secret",
        "PIONEX_MCP_TRADING_ENABLED": "false"
      }
    }
  }
}
```

## Uso típico

```text
Usuario: ¿a cuánto está el BTC?
IA → get_price("BTC_USDT")            # precio vivo, nunca de memoria

Usuario: compra 20 USDT de ETH
IA → prepare_order(symbol="ETH_USDT", side="BUY", order_type="MARKET", amount="20")
     → muestra el resumen y el token al usuario
Usuario: confirmo
IA → confirm_action(confirmation_token="ab12cd34ef56-9f3a")
```

Si el trading está deshabilitado, `prepare_order` responde con el mensaje exacto de qué variable de entorno debe activar el operador.

## Cómo evita alucinaciones

1. **Vocabularios cerrados**: `side`, `order_type`, `interval`, `market_type`, `grid_type`, `product_type` se validan contra whitelists que replican la doc oficial de Pionex; un valor inventado devuelve la lista completa de valores válidos.
2. **Símbolos verificados en vivo** contra `GET /api/v1/common/symbols` (caché 10 min), con sugerencias de corrección (`BTCUSDT` → «¿quisiste decir BTC_USDT?»).
3. **Dos fases con token ligado a parámetros**: el token contiene un hash SHA-256 de la acción y sus parámetros; en la confirmación se ejecutan los parámetros **almacenados en el servidor**, no los que la IA pase.
4. **Guardas numéricas del operador**: tope de nocional y desviación de precio se comprueban contra datos vivos del exchange.
5. **Procedencia obligatoria**: la IA recibe la instrucción (en las *instructions* del servidor y en cada envelope) de reportar solo campos presentes en `data`.
6. **Errores verbatim** + **auditoría JSONL** de todo lo preparado y ejecutado.

## Estructura

```
src/mcp_pionex/
├── server.py      # FastMCP, instructions anti-alucinación, tools meta
├── config.py      # Settings por entorno (conservador por defecto)
├── safety.py      # vocabularios, verificación de símbolos, 2-fases, límites, audit
├── client.py      # singletons perezosos de los clientes pionex_py
├── actions.py     # registro de ejecutores para confirm_action
└── tools/
    ├── market.py   # 9 tools públicas de mercado
    ├── account.py  # 8 tools de cuenta (solo lectura)
    ├── trading.py  # 6 tools de trading (2 fases)
    ├── bots.py     # 6 tools de bots
    └── earn.py     # 7 tools de Dual Investment
```

## Uso con un LLM local

Tres vías (detalle en [`docs/GUIA.md`](docs/GUIA.md#6-integración-con-un-llm-local)):

- **LM Studio**: soporta MCP nativamente — pega el mismo bloque `mcpServers` en su `mcp.json`.
- **Ollama + [mcphost](https://github.com/mark3labs/mcphost)**: `mcphost -m ollama:qwen3 --config mcp.json`.
- **Puente incluido**: `uv run examples/ollama_bridge.py "¿a cuánto está el BTC?"` — bucle agéntico completo contra Ollama con las 43 tools.

Con modelos locales, mantén `PIONEX_MCP_TRADING_ENABLED=false` salvo supervisión estrecha: las guardas del servidor son las mismas, pero los modelos pequeños alucinan más.

## Documentación

- [`docs/GUIA.md`](docs/GUIA.md) — guía completa: instalación, configuración, integraciones (Claude y LLM local), flujos, seguridad operacional, troubleshooting y extensión.
- [`docs/INFORME.md`](docs/INFORME.md) — informe de capacidades y verificación.
- [`CLAUDE.md`](CLAUDE.md) — guía interna del proyecto para agentes IA.
- Doc oficial de la API: <https://pionex-doc.gitbook.io/apidocs/>

## Licencia

MIT

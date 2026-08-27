# MCP-Pionex

[![CI](https://github.com/alejandrorodm/MCP-Pionex/actions/workflows/ci.yml/badge.svg)](https://github.com/alejandrorodm/MCP-Pionex/actions/workflows/ci.yml)
[![Listed on Glama](https://img.shields.io/badge/Glama-listed-blueviolet)](https://glama.ai/mcp/servers/alejandrorodm/MCP-Pionex)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)
[![MCP SDK 2.x](https://img.shields.io/badge/MCP%20SDK-2.x-black)](https://github.com/modelcontextprotocol/python-sdk)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

A **Model Context Protocol** server for the [Pionex](https://www.pionex.com) exchange, built in Python on top of [`pionex_py`](https://pypi.org/project/pionex-py/), designed around one question: **how do you let an LLM touch real money without letting it hallucinate?**

It exposes **56 tools** — market data, technical analysis, account, spot trading, spot/futures grid bots and Dual Investment — behind a strict safety layer: read-only by default, two-phase commit for every state change, live validation of every symbol and price, operator-set hard limits the model cannot override, idempotency keys, provenance on every response and a local audit trail.

Serves over **stdio** or **Streamable HTTP**. Works with **Claude Code / Claude Desktop**, **Cursor**, and **local LLMs** (LM Studio, Ollama via `mcphost` or the [bundled bridge](examples/ollama_bridge.py)).

> 🇪🇸 Guía completa en español: [`docs/GUIA.md`](docs/GUIA.md) · Informe de capacidades: [`docs/INFORME.md`](docs/INFORME.md)

---

## Why this server

Most exchange MCP servers are thin API wrappers: the model calls `new_order` and the order goes out. That is fine for a demo and dangerous with a funded account, because language models invent symbols, misremember prices and re-issue calls when a response is slow.

MCP-Pionex treats the model as an untrusted client:

| Guardrail | What it means in practice |
|---|---|
| **Read-only by default** | Trading, bots, futures and earn writes are off until the *operator* enables each one by environment variable. The conversation cannot flip them. |
| **Two-phase commit** | Every state change is `prepare_*` → `confirm_action`. Prepare validates everything against live data and returns a single-use token bound (SHA-256) to the validated parameters, with a TTL. Confirm executes the **server-stored** parameters — nothing the model passes at confirm time can change them. |
| **Idempotency keys** | Every prepared order carries a `clientOrderId` (server-minted if absent) and returns it. If a confirm response is lost, the model is instructed to reconcile with `get_order_by_client_id` before re-preparing — never to resubmit blindly. |
| **Live symbol verification** | A pair must exist on Pionex *right now* (`GET /common/symbols`, 10-min cache). `BTCUSDT` gets "did you mean `BTC_USDT`?", not a request. |
| **Hard numeric limits** | Per-action notional cap, max LIMIT-price deviation from the live mid-price, max leverage for futures grids, optional symbol whitelist. All operator-set, all enforced server-side. |
| **Closed vocabularies** | `side`, `order_type`, `interval`, `grid_type`, `trend`, `product_type`… are validated against whitelists mirroring the Pionex docs; an invalid value returns the full valid list so the model self-corrects. |
| **Provenance envelopes** | Every response carries `source` (endpoint), `fetched_at` (UTC) and a `computed` flag separating exchange facts from server-derived values (indicators, mid-price, portfolio weights). |
| **Verbatim errors** | Pionex API errors pass through with their original `code` and `message`. Never paraphrased. |
| **MCP annotations** | All 56 tools declare `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`, so MCP clients can require human approval on destructive calls. |
| **Audit log** | Every prepare, confirm and cancel is appended to a local JSONL file. |

## Tool catalogue

| Group | Tools | Access |
|---|---|---|
| **Meta** (2) | `get_server_status`, `get_safety_rules` | always |
| **Market** (9) | `list_symbols`, `get_symbol_info`, `get_price`, `get_ticker_24h`, `get_book_ticker`, `get_depth`, `get_recent_trades`, `get_klines`, `get_klines_history` | public |
| **Technical analysis** (5) | `get_emas`, `get_indicators` (RSI, MACD, ATR, Bollinger, SMA/EMA), `detect_fvg`, `detect_order_blocks`, `get_market_structure` | public · all `computed` |
| **Account** (8) | `get_balances`, `get_portfolio`, `get_open_orders`, `get_order`, `get_order_by_client_id`, `get_order_history`, `get_fills`, `get_fills_by_order` | API key |
| **Spot trading** (7) | `prepare_order`, `prepare_cancel_all_orders`, `prepare_cancel_orders`, `cancel_order`, `compute_rebalance_plan`, `prepare_rebalance`, `confirm_action` | `TRADING_ENABLED` |
| **Bots** (14) | reads: `list_bot_orders`, `get_spot_grid`, `get_futures_grid`, `get_smart_copy`, `get_grid_ai_strategy`, `check_spot_grid_params`, `check_futures_grid_params` · spot grid: `prepare_create_spot_grid`, `prepare_adjust_spot_grid`, `prepare_invest_in_spot_grid`, `prepare_extract_spot_grid_profit`, `prepare_cancel_spot_grid` · futures grid: `prepare_create_futures_grid`, `prepare_cancel_futures_grid` | reads: API key · spot: `BOTS_ENABLED` · futures: `BOTS_ENABLED` + `FUTURES_ENABLED` |
| **Earn / Dual Investment** (11) | `list_dual_symbols`, `list_dual_products`, `get_dual_prices`, `get_dual_index`, `get_dual_delivery_prices`, `get_dual_balances`, `query_dual_invests`, `get_dual_records`, `prepare_dual_invest`, `prepare_dual_revoke`, `prepare_dual_collect` | reads: public / API key · writes: `EARN_ENABLED` |

Every tool description follows the same structure — purpose, when to use it versus sibling tools, arguments with ranges, return shape, requirements — so both models and humans can pick the right one. Field-level detail: [`docs/INFORME.md`](docs/INFORME.md).

## Quick start

**Requirements:** Python ≥ 3.11, [`uv`](https://docs.astral.sh/uv/) (or pip). A Pionex API key is only needed for account/trading tools; market data and technical analysis work without one.

```bash
git clone https://github.com/alejandrorodm/MCP-Pionex
cd MCP-Pionex
uv sync
```

### Claude Code

```bash
claude mcp add pionex \
  --env PIONEX_API_KEY=your_key \
  --env PIONEX_API_SECRET=your_secret \
  -- uv --directory /absolute/path/to/MCP-Pionex run mcp-pionex
```

### Claude Desktop / Cursor / any MCP client (`mcp.json`)

```json
{
  "mcpServers": {
    "pionex": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/MCP-Pionex", "run", "mcp-pionex"],
      "env": {
        "PIONEX_API_KEY": "your_key",
        "PIONEX_API_SECRET": "your_secret",
        "PIONEX_MCP_TRADING_ENABLED": "false"
      }
    }
  }
}
```

### Remote / multi-client: Streamable HTTP

```bash
uv run mcp-pionex --transport streamable-http --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000/mcp
```

Same server, same guardrails, served over the MCP **Streamable HTTP** transport instead of stdio, so several clients (or a client on another machine) can share one process. Keep it on localhost or behind an authenticating reverse proxy: the API credentials live in this process.

### Local LLMs

- **LM Studio** — native MCP support: paste the same `mcpServers` block into its `mcp.json`.
- **Ollama + [mcphost](https://github.com/mark3labs/mcphost)** — `mcphost -m ollama:qwen3 --config mcp.json`.
- **Bundled bridge** — `uv run examples/ollama_bridge.py "what's BTC at?"` runs a full agentic loop against Ollama with all 56 tools.

Keep `PIONEX_MCP_TRADING_ENABLED=false` with small local models unless closely supervised: the server guardrails are identical, but small models hallucinate more.

## Configuration

Everything is controlled by environment variables (template in [`.env.example`](.env.example)). Defaults are the most conservative possible.

| Variable | Default | Description |
|---|---|---|
| `PIONEX_API_KEY` / `PIONEX_API_SECRET` | — | API credentials. Server environment only — **never in the chat**. |
| `PIONEX_MCP_TRADING_ENABLED` | `false` | Enable spot orders, cancels and rebalancing |
| `PIONEX_MCP_BOTS_ENABLED` | `false` | Enable spot grid create / adjust / invest / close |
| `PIONEX_MCP_FUTURES_ENABLED` | `false` | Enable futures (leveraged) grids — requires `BOTS_ENABLED` too |
| `PIONEX_MCP_EARN_ENABLED` | `false` | Enable Dual Investment invest / revoke / collect |
| `PIONEX_MCP_MAX_ORDER_NOTIONAL` | `100` | Max quote-currency notional per order, investment, margin or rebalance leg |
| `PIONEX_MCP_MAX_PRICE_DEVIATION_PCT` | `10` | Max deviation of a LIMIT price from the live mid-price |
| `PIONEX_MCP_MAX_LEVERAGE` | `3` | Max leverage for futures grids |
| `PIONEX_MCP_SYMBOL_WHITELIST` | empty | e.g. `BTC_USDT,ETH_USDT` to restrict the tradable universe |
| `PIONEX_MCP_CONFIRMATION_TTL` | `120` | Seconds a confirmation token stays valid |
| `PIONEX_MCP_AUDIT_LOG` | `~/.mcp_pionex/audit.jsonl` | Audit trail path |

Recommended postures: **query only** (default, zero risk) → **bounded trading** (`TRADING_ENABLED` + low notional + whitelist) → **full** (all gates, notional at your risk tolerance) → **leveraged** (add `FUTURES_ENABLED` with a low `MAX_LEVERAGE`).

## How a trade flows

```text
User:  what's ETH at?
AI  →  get_price("ETH_USDT")                     # live, never from memory

User:  buy 20 USDT of ETH
AI  →  prepare_order(symbol="ETH_USDT", side="BUY", order_type="MARKET", amount="20")
       ← { confirmation_token: "ab12cd34ef56-9f3a",
           client_order_id: "mcp-7c1e9a2b4d60",
           summary: "BUY MARKET on ETH_USDT: spend amount=20 (quote) | est. notional ≈ 20.0000 | ...",
           expires_in_seconds: 120 }
       shows the summary and waits

User:  confirm
AI  →  confirm_action("ab12cd34ef56-9f3a")       # executes the STORED params
       ← { action: "place_order", result: { orderId: 1234567, ... } }
```

If trading is disabled, `prepare_order` returns the exact environment variable the operator has to set. If the token is reused, expired, or the notional exceeds the cap, the error says so and tells the model what to do instead. If the confirm response is lost, `get_order_by_client_id("mcp-7c1e9a2b4d60")` tells you whether the order was placed.

## Project layout

```
src/mcp_pionex/
├── server.py      # MCPServer, anti-hallucination instructions, meta tools
├── config.py      # operator settings from the environment (conservative defaults)
├── safety.py      # vocabularies, live symbol check, two-phase commit, limits,
│                  # idempotency keys, annotations, envelopes, audit
├── client.py      # lazy singletons over pionex_py clients
├── actions.py     # executor registry for confirm_action
├── ta.py          # pure technical-analysis maths (offline-tested)
└── tools/
    ├── market.py    # 9 public market tools
    ├── analysis.py  # 5 technical-analysis tools
    ├── account.py   # 8 read-only account tools
    ├── trading.py   # 7 spot-trading tools (two-phase)
    ├── bots.py      # 14 spot/futures grid + smart-copy tools
    └── earn.py      # 11 Dual Investment tools
```

## Development

```bash
uv run --with pytest pytest tests/ -q       # 45 offline tests: safety, annotations, idempotency, TA
uv run python -c "from mcp_pionex.server import mcp; import asyncio; \
  print(len(asyncio.run(mcp.list_tools())), 'tools')"   # → 56 tools
```

CI runs the suite on Python 3.11 and 3.12 and asserts the tool count. See [`CHANGELOG.md`](CHANGELOG.md) for release history and [`CLAUDE.md`](CLAUDE.md) for the contributor guide (tool pattern, how to add a two-phase action).

## Known limits

- No WebSocket streams (MCP is request/response) — use `get_klines` / `get_price` for snapshots.
- Futures grid *adjust* / *reduce*, smart-copy writes, user signals and Earn Arbitrage are not exposed.
- Pending confirmation tokens live in memory: restarting the server invalidates them (by design).
- Pionex caps klines at 500 per request (paged up to 5000 here) and order history at 200.

## Related

- [`pionex_py`](https://github.com/alejandrorodm/pionex_py) — the underlying REST/WebSocket client (PyPI: `pionex-py`).
- [Pionex API docs](https://pionex-doc.gitbook.io/apidocs/) · [Pionex AI Kit](https://github.com/pionex-official/pionex-ai-kit) (official TypeScript MCP, no safety layer).
- [Model Context Protocol](https://modelcontextprotocol.io) · [Glama listing](https://glama.ai/mcp/servers/alejandrorodm/MCP-Pionex).

## License

MIT — © Alejandro Rodríguez Moreno

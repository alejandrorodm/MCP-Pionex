# Changelog

## 1.2.0 — 2026-08-27

### Added
- **Streamable HTTP transport**: `mcp-pionex --transport streamable-http
  [--host] [--port] [--stateless]` alongside the default stdio.
- **MCP tool annotations** on all 56 tools (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) so clients can gate destructive calls.
- **Idempotency keys**: `prepare_order` always sets a `clientOrderId`
  (server-minted `mcp-…` when not supplied) and returns it;
  `prepare_dual_invest` does the same with `clientDualId`. Server instructions
  tell the model to reconcile via `get_order_by_client_id` /
  `query_dual_invests` before re-preparing after a lost response.
- **Futures grid bots** (`get_futures_grid`, `check_futures_grid_params`,
  `prepare_create_futures_grid`, `prepare_cancel_futures_grid`) behind a new
  `PIONEX_MCP_FUTURES_ENABLED` gate and a `PIONEX_MCP_MAX_LEVERAGE` cap.
- **Spot grid lifecycle**: `prepare_adjust_spot_grid`,
  `prepare_invest_in_spot_grid`, `prepare_extract_spot_grid_profit`;
  `prepare_cancel_spot_grid` accepts `close_sell_model` (`SELL`/`HOLD`).
- `get_smart_copy` (read-only).
- **Trading**: `prepare_cancel_orders` — cancel a verified list of orderIds.
- **Dual Investment**: `get_dual_delivery_prices`, `get_dual_records`,
  `query_dual_invests`, `prepare_dual_collect`.
- Tests: `test_annotations.py` (count, annotations, description structure),
  `test_idempotency.py` (client ids, leverage cap, futures gate).

### Changed
- Every tool description rewritten in English with a fixed structure —
  purpose, when to use vs. sibling tools, `Args` with ranges, `Returns`
  shape, requirements — following Glama's Tool Definition Quality criteria.
- Server `instructions` updated (perpetual symbol format, reconciliation
  rule, leverage cap).
- `MCPServer` now reports its `version`.

## 1.1.0

- Technical-analysis tools: EMAs, indicator panel, FVG, order blocks,
  market structure (`ta.py`, offline-tested).

## 1.0.0

- Initial release: market, account, spot trading, spot grid and Dual
  Investment tools with the anti-hallucination safety layer.

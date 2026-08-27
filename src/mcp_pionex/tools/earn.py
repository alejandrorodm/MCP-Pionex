"""
Earn / Dual Investment tools. Product listings, prices and delivery prices
are public; balances/records need credentials; invest/revoke/collect are
two-phase and gated behind PIONEX_MCP_EARN_ENABLED.
"""

from mcp_pionex import safety
from mcp_pionex.actions import executor
from mcp_pionex.client import earn_client
from mcp_pionex.safety import (
    PREPARE,
    READ,
    guarded,
    require_credentials,
    require_earn,
    validate_enum,
)


@executor("dual_invest")
def _execute_invest(params: dict) -> dict:
    require_earn()
    response = earn_client().invest(**params)
    return response.get("data", response)


@executor("dual_revoke")
def _execute_revoke(params: dict) -> dict:
    require_earn()
    response = earn_client().revoke_invest(**params)
    return response.get("data", response)


@executor("dual_collect")
def _execute_collect(params: dict) -> dict:
    require_earn()
    response = earn_client().collect(**params)
    return response.get("data", response)


def register(mcp):

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/symbols")
    def list_dual_symbols(base: str = "") -> dict:
        """List the pairs supported by Dual Investment and their quote
        convention.

        Call first: BTC/ETH products use quote 'USDXO' (USDC+USDT bundle),
        other coins use 'USDT' — take the quote from here, do not assume.

        Args:
          base: optional base coin filter, e.g. 'BTC'.

        Returns `data.symbols` verbatim. Public — no credentials."""
        response = earn_client().list_symbols(base=base or None)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/openProducts")
    def list_dual_products(base: str, quote: str, product_type: str,
                           currency: str = "") -> dict:
        """List the Dual Investment products currently open for
        subscription, with strike prices, expiry and indicative yields.

        Use to find a productId; then get_dual_prices for the live `profit`
        value required by prepare_dual_invest.

        Args:
          base / quote: from list_dual_symbols (e.g. 'BTC' / 'USDXO').
          product_type: 'DUAL_BASE' (invest the base coin, e.g. BTC, earn
            if price ends above strike) or 'DUAL_CURRENCY' (invest the
            quote, e.g. USDT, receive base if price ends below strike).
          currency: optional settlement currency filter (e.g. 'USDT').

        Returns `data.products` verbatim (productId, strike, deliveryTime,
        apy…). Public — no credentials."""
        validate_enum(product_type, safety.VALID_DUAL_TYPES, "product_type")
        response = earn_client().list_open_products(
            base=base, quote=quote, type=product_type,
            currency=currency or None,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/prices")
    def get_dual_prices(base: str, quote: str, product_ids: str) -> dict:
        """Return the current yield (`profit`) of specific Dual Investment
        products.

        The `profit` passed to prepare_dual_invest MUST come from this call
        — a stale or invented value is rejected by the exchange with
        INVALID_PROFIT.

        Args:
          base / quote: e.g. 'BTC' / 'USDXO'.
          product_ids: comma-separated productIds from list_dual_products.

        Returns `data.prices` verbatim (productId → profit and related
        fields). Public — no credentials."""
        response = earn_client().get_prices(
            base=base, quote=quote, productIds=product_ids,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/index")
    def get_dual_index(base: str, quote: str) -> dict:
        """Return the real-time index price used by Dual Investment for a
        pair (the reference against which strikes settle).

        Args:
          base / quote: e.g. 'BTC' / 'USDXO'.

        Returns the exchange's index object verbatim. Public — no
        credentials."""
        response = earn_client().get_index(base=base, quote=quote)
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/deliveryPrices")
    def get_dual_delivery_prices(base: str, quote: str = "",
                                 start_time_ms: int = 0,
                                 end_time_ms: int = 0) -> dict:
        """Return historical Dual Investment delivery (settlement) prices for
        a pair.

        Use to explain past settlements or to check where recent expiries
        settled relative to strikes.

        Args:
          base: e.g. 'BTC'. quote: optional, e.g. 'USDXO'.
          start_time_ms / end_time_ms: optional epoch-ms range (0 = unset).

        Returns `data` verbatim (list of {deliveryTime, price…}). Public —
        no credentials."""
        response = earn_client().get_delivery_prices(
            base=base, quote=quote or None,
            startTime=start_time_ms or None, endTime=end_time_ms or None,
        )
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/balances")
    def get_dual_balances() -> dict:
        """Return the account's Dual Investment balances / open positions.

        Use for "what do I have in Dual Investment right now". For
        settled history use get_dual_records; for specific orders use
        query_dual_invests.

        Returns `data` verbatim. Requires API credentials (read)."""
        require_credentials()
        response = earn_client().get_balances()
        return response["data"]

    @mcp.tool(annotations=READ)
    @guarded("POST /api/v1/earn/dual/invests")
    def query_dual_invests(client_dual_ids: str, base: str = "") -> dict:
        """Look up Dual Investment orders by their clientDualId(s).

        Use to RECONCILE an investment whose confirm_action response was
        lost: prepare_dual_invest returns the clientDualId it will use.
        Read-only despite being a POST.

        Args:
          client_dual_ids: comma-separated clientDualIds.
          base: optional base coin filter.

        Returns `data` verbatim (list of invest objects with status).
        Requires API credentials (read)."""
        require_credentials()
        ids = [s.strip() for s in client_dual_ids.split(",") if s.strip()]
        safety.require(1 <= len(ids) <= 50, "provide between 1 and 50 clientDualIds")
        response = earn_client().batch_query_invests(
            base=base or None, clientDualIds=ids,
        )
        return response.get("data", response)

    @mcp.tool(annotations=READ)
    @guarded("GET /api/v1/earn/dual/records")
    def get_dual_records(base: str, end_time_ms: int, quote: str = "",
                         status_filter: str = "ALL", start_time_ms: int = 0,
                         limit: int = 50) -> dict:
        """Return the account's Dual Investment history (settled and
        unsettled orders) for a base coin.

        Use after settlement to see outcomes and to find orders eligible for
        prepare_dual_collect.

        Args:
          base: e.g. 'BTC'.
          end_time_ms: REQUIRED epoch-ms upper bound (the exchange demands
            it; use the current time for "up to now").
          quote: optional, e.g. 'USDXO'.
          status_filter: 'ALL', 'SETTLED' or 'UNSETTLED'.
          start_time_ms: optional epoch-ms lower bound (0 = unset).
          limit: records to return, 1-200 (default 50).

        Returns `data` verbatim. Requires API credentials (read)."""
        require_credentials()
        validate_enum(status_filter, safety.VALID_DUAL_FILTERS, "status_filter")
        safety.require(end_time_ms > 0, "end_time_ms is required (epoch ms)")
        safety.require(1 <= limit <= 200, "limit must be between 1 and 200")
        response = earn_client().get_records(
            base=base, endTime=end_time_ms, quote=quote or None,
            filter=status_filter, startTime=start_time_ms or None, limit=limit,
        )
        return response["data"]

    # ------------------------------------------------------------------ writes

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing invested")
    def prepare_dual_invest(base: str, product_id: str, profit: str,
                            base_amount: str = "", currency_amount: str = "",
                            client_dual_id: str = "") -> dict:
        """STEP 1 of 2 to subscribe to a Dual Investment product. Returns a
        confirmation token; nothing is invested until confirm_action.

        Workflow: list_dual_products → get_dual_prices (for `profit`) →
        this tool → show summary → confirm_action. Explain to the user that
        settlement may deliver the other coin depending on the strike.

        Args:
          base: e.g. 'BTC'.
          product_id: productId from list_dual_products.
          profit: the live value from get_dual_prices, verbatim.
          base_amount OR currency_amount: provide EXACTLY ONE (string);
            base_amount for DUAL_BASE products, currency_amount for
            DUAL_CURRENCY. Capped by PIONEX_MCP_MAX_ORDER_NOTIONAL.
          client_dual_id: optional idempotency key (1-32 chars
            [A-Za-z0-9_-]); the server mints one ('dual-…') if empty.

        Returns confirmation_token, client_dual_id, validated_params and
        summary. Reconcile with query_dual_invests if the confirm response
        is lost. Requires credentials and PIONEX_MCP_EARN_ENABLED=true."""
        require_earn()
        safety.require(
            bool(base_amount) != bool(currency_amount),
            "Provide exactly one of base_amount or currency_amount.",
        )
        invested = float(base_amount or currency_amount)
        safety.check_notional_cap(invested, "prepare_dual_invest")
        cid = safety.client_order_id(client_dual_id, prefix="dual")
        params = {"base": base, "productId": product_id, "profit": profit,
                  "clientDualId": cid}
        if base_amount:
            params["baseAmount"] = base_amount
        else:
            params["currencyAmount"] = currency_amount
        summary = (
            f"Dual invest on {base} product {product_id}: "
            f"{base_amount + ' ' + base if base_amount else currency_amount + ' (quote)'} "
            f"at profit {profit} | client_dual_id={cid}"
        )
        prepared = safety.prepare_action("dual_invest", params, summary)
        prepared["client_dual_id"] = cid
        return prepared

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing revoked")
    def prepare_dual_revoke(base: str, product_id: str,
                            client_dual_id: str) -> dict:
        """STEP 1 of 2 to REVOKE an unsettled Dual Investment order. Returns
        a confirmation token; nothing is revoked until confirm_action.

        Use when the user changes their mind before settlement. Ids must
        come from get_dual_balances / query_dual_invests.

        Args:
          base: e.g. 'BTC'. product_id: productId of the order.
          client_dual_id: clientDualId of the order.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_EARN_ENABLED=true."""
        require_earn()
        return safety.prepare_action(
            "dual_revoke",
            {"base": base, "productId": product_id,
             "clientDualId": client_dual_id},
            f"Revoke dual investment {client_dual_id} on {base} product {product_id}",
        )

    @mcp.tool(annotations=PREPARE)
    @guarded("validation only — nothing collected")
    def prepare_dual_collect(base: str, product_id: str,
                             client_dual_id: str) -> dict:
        """STEP 1 of 2 to COLLECT (claim) the proceeds of a settled Dual
        Investment order. Returns a confirmation token; nothing is claimed
        until confirm_action.

        Use after get_dual_records shows a SETTLED order. Ids must come
        from exchange data, never from memory.

        Args:
          base: e.g. 'BTC'. product_id: productId of the settled order.
          client_dual_id: clientDualId of the settled order.

        Returns confirmation_token, validated_params and summary. Requires
        credentials and PIONEX_MCP_EARN_ENABLED=true."""
        require_earn()
        return safety.prepare_action(
            "dual_collect",
            {"base": base, "productId": product_id,
             "clientDualId": client_dual_id},
            f"Collect settled dual investment {client_dual_id} on {base} product {product_id}",
        )

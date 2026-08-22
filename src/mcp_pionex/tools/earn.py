"""
Earn / Dual Investment tools. Product listings and prices are public;
balances need credentials; invest/revoke/collect are two-phase and gated
behind PIONEX_MCP_EARN_ENABLED.
"""

from mcp_pionex import safety
from mcp_pionex.actions import executor
from mcp_pionex.client import earn_client
from mcp_pionex.safety import guarded, require_credentials, require_earn, validate_enum


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


def register(mcp):

    @mcp.tool()
    @guarded("GET /api/v1/earn/dual/symbols")
    def list_dual_symbols(base: str = "") -> dict:
        """Pairs supported by Dual Investment. Note Pionex's quote convention:
        BTC/ETH pairs use quote 'USDXO' (USDC+USDT bundled); others use 'USDT'."""
        response = earn_client().list_symbols(base=base or None)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/earn/dual/openProducts")
    def list_dual_products(base: str, quote: str, product_type: str,
                           currency: str = "") -> dict:
        """Dual-investment products currently open for subscription.
        product_type MUST be 'DUAL_BASE' (invest the base coin, e.g. BTC) or
        'DUAL_CURRENCY' (invest the quote, e.g. USDT). Yields and strike
        prices come verbatim from the exchange."""
        validate_enum(product_type, safety.VALID_DUAL_TYPES, "product_type")
        response = earn_client().list_open_products(
            base=base, quote=quote, type=product_type,
            currency=currency or None,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/earn/dual/prices")
    def get_dual_prices(base: str, quote: str, product_ids: str) -> dict:
        """Current prices/yields for specific dual products (comma-separated
        productIds). The `profit` value used when investing MUST come from
        here — a stale or invented profit is rejected by the exchange."""
        response = earn_client().get_prices(
            base=base, quote=quote, productIds=product_ids,
        )
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/earn/dual/index")
    def get_dual_index(base: str, quote: str) -> dict:
        """Underlying index price for a dual-investment pair."""
        response = earn_client().get_index(base=base, quote=quote)
        return response["data"]

    @mcp.tool()
    @guarded("GET /api/v1/earn/dual/balances")
    def get_dual_balances() -> dict:
        """The account's dual-investment balances/positions."""
        require_credentials()
        response = earn_client().get_balances()
        return response["data"]

    @mcp.tool()
    @guarded("validation only — nothing invested")
    def prepare_dual_invest(base: str, product_id: str, profit: str,
                            base_amount: str = "", currency_amount: str = "",
                            client_dual_id: str = "") -> dict:
        """STEP 1 of 2 to subscribe to a dual-investment product. Provide
        EXACTLY ONE of base_amount or currency_amount. `profit` must be the
        live value from get_dual_prices. Returns a confirmation token."""
        require_earn()
        safety.require(
            bool(base_amount) != bool(currency_amount),
            "Provide exactly one of base_amount or currency_amount.",
        )
        invested = float(base_amount or currency_amount)
        safety.check_notional_cap(invested, "prepare_dual_invest")
        params = {"base": base, "productId": product_id, "profit": profit}
        if base_amount:
            params["baseAmount"] = base_amount
        else:
            params["currencyAmount"] = currency_amount
        if client_dual_id:
            params["clientDualId"] = client_dual_id
        summary = (
            f"Dual invest on {base} product {product_id}: "
            f"{base_amount + ' ' + base if base_amount else currency_amount + ' (quote)'} "
            f"at profit {profit}"
        )
        return safety.prepare_action("dual_invest", params, summary)

    @mcp.tool()
    @guarded("validation only — nothing revoked")
    def prepare_dual_revoke(base: str, product_id: str,
                            client_dual_id: str) -> dict:
        """STEP 1 of 2 to revoke an unsettled dual investment. Returns a
        confirmation token."""
        require_earn()
        return safety.prepare_action(
            "dual_revoke",
            {"base": base, "productId": product_id,
             "clientDualId": client_dual_id},
            f"Revoke dual investment {client_dual_id} on {base} product {product_id}",
        )

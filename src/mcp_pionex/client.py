"""
Lazy singleton wrappers around the pionex_py clients.

Clients are created on first use so a missing API key only fails the tools
that actually need it, and public market-data tools always work.
"""

from functools import lru_cache

from pionex_python.restful.Account import Account
from pionex_python.restful.Bot import Bot
from pionex_python.restful.Common import Common
from pionex_python.restful.EarnDual import EarnDual
from pionex_python.restful.Markets import Markets
from pionex_python.restful.Orders import Orders
from pionex_python.restful.Trade import Trade

from mcp_pionex.config import SETTINGS


def _normalized(client):
    # pionex_py's base_url ends with '/' while url paths start with '/';
    # Pionex's router 404s the resulting double slash. Strip it here.
    client.base_url = client.base_url.rstrip("/")
    return client


@lru_cache(maxsize=1)
def common_client() -> Common:
    return _normalized(Common())


@lru_cache(maxsize=1)
def markets_client() -> Markets:
    return _normalized(Markets())


@lru_cache(maxsize=1)
def account_client() -> Account:
    return _normalized(Account(SETTINGS.api_key, SETTINGS.api_secret))


@lru_cache(maxsize=1)
def orders_client() -> Orders:
    return _normalized(Orders(SETTINGS.api_key, SETTINGS.api_secret))


@lru_cache(maxsize=1)
def bot_client() -> Bot:
    return _normalized(Bot(SETTINGS.api_key, SETTINGS.api_secret))


@lru_cache(maxsize=1)
def earn_client() -> EarnDual:
    return _normalized(EarnDual(SETTINGS.api_key, SETTINGS.api_secret))


@lru_cache(maxsize=1)
def trade_client() -> Trade:
    client = Trade(SETTINGS.api_key, SETTINGS.api_secret)
    for sub in (client.account, client.orders, client.markets, client.common):
        _normalized(sub)
    return client

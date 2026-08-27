"""
Anti-hallucination and safety layer.

Every rule here exists to make it impossible for a model to act on invented
data:

1.  **Closed vocabularies** — sides, order types, intervals, market types and
    grid types are validated against hardcoded whitelists that mirror the
    Pionex API docs. Anything else is rejected with the full list of valid
    values, so the model self-corrects instead of guessing again.
2.  **Live symbol verification** — a symbol is only accepted if it exists on
    the exchange *right now* (cached 10 min). A hallucinated pair can never
    reach the API.
3.  **Two-phase commit** — every state-changing action must first be
    *prepared*. Preparation validates everything, snapshots the exact
    parameters, and returns a one-time confirmation token that is a hash of
    those parameters. Execution only happens when the token is presented
    back, and the executed parameters are the *stored* ones — the model
    cannot swap in different values between prepare and confirm.
4.  **Hard numeric limits** — notional caps and price-deviation guards are
    enforced server-side from operator config; the model cannot raise them.
5.  **Provenance envelopes** — every response carries the endpoint it came
    from and a fetch timestamp, and derived values are explicitly marked
    ``computed`` so the model can distinguish exchange facts from arithmetic.
6.  **Verbatim errors** — API errors are passed through with their original
    code and message, never paraphrased.
7.  **Audit trail** — every prepared and executed action is appended to a
    local JSONL audit log.
"""

import functools
import re
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone

from mcp.types import ToolAnnotations

from mcp_pionex.config import SETTINGS

# ---------------------------------------------------------------------------
# MCP tool annotations (spec hints consumed by clients such as Claude Desktop,
# Cursor and Glama). Every tool in this server declares exactly one of these.
# ---------------------------------------------------------------------------

#: Local introspection — no network, no side effects.
LOCAL = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                        idempotent_hint=True, open_world_hint=False)
#: Reads exchange data (public or account). Never changes state.
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                       idempotent_hint=True, open_world_hint=True)
#: STEP 1 of the two-phase commit: validates against live data and stores a
#: pending action server-side. Touches no exchange state, but is not
#: read-only (it creates a token and an audit entry) and not idempotent
#: (each call mints a fresh token).
PREPARE = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                          idempotent_hint=False, open_world_hint=True)
#: Changes exchange state (orders, bots, investments). Marked idempotent
#: because a confirmation token is single-use: repeating the call cannot
#: execute the action twice.
EXECUTE = ToolAnnotations(read_only_hint=False, destructive_hint=True,
                          idempotent_hint=True, open_world_hint=True)

# ---------------------------------------------------------------------------
# Closed vocabularies (mirror pionex_py validators + Pionex API docs)
# ---------------------------------------------------------------------------

VALID_SIDES = ("BUY", "SELL")
VALID_ORDER_TYPES = ("LIMIT", "MARKET")
VALID_MARKET_TYPES = ("SPOT", "PERP")
VALID_KLINE_INTERVALS = ("1M", "5M", "15M", "30M", "60M", "4H", "8H", "12H", "1D")
VALID_GRID_TYPES = ("arithmetic", "geometric")
VALID_TRENDS = ("long", "short", "no_trend")
VALID_DUAL_TYPES = ("DUAL_BASE", "DUAL_CURRENCY")
VALID_CLOSE_SELL_MODELS = ("SELL", "HOLD")
VALID_DUAL_FILTERS = ("ALL", "SETTLED", "UNSETTLED")

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


class SafetyError(Exception):
    """Raised when a guardrail blocks an action. The message is designed to
    tell the model exactly what is valid so it stops guessing."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SafetyError(message)


def validate_enum(value, valid: tuple, name: str):
    require(
        value in valid,
        f"Invalid {name}: {value!r}. Valid values (exact, case-sensitive): {list(valid)}. "
        f"Do not invent values — use one of these verbatim.",
    )
    return value


# ---------------------------------------------------------------------------
# Live symbol verification
# ---------------------------------------------------------------------------

_SYMBOL_CACHE: dict = {}   # market_type -> {"at": ts, "symbols": {name: info}}
_SYMBOL_CACHE_TTL = 600.0


def _load_symbols(market_type: str) -> dict:
    from mcp_pionex.client import common_client

    entry = _SYMBOL_CACHE.get(market_type)
    if entry and (time.monotonic() - entry["at"]) < _SYMBOL_CACHE_TTL:
        return entry["symbols"]
    response = common_client().market_data(market_type=market_type)
    symbols = {s["symbol"]: s for s in response["data"]["symbols"]}
    _SYMBOL_CACHE[market_type] = {"at": time.monotonic(), "symbols": symbols}
    return symbols


def verify_symbol(symbol: str, market_type: str = "SPOT") -> dict:
    """Return the live exchange metadata for ``symbol`` or raise SafetyError.

    This is the rule that makes hallucinated trading pairs impossible: the
    symbol must exist on Pionex *now*, spelled exactly as the exchange
    spells it (e.g. 'BTC_USDT', not 'BTCUSDT' or 'BTC/USDT').
    """
    validate_enum(market_type, VALID_MARKET_TYPES, "market_type")
    require(bool(symbol), "symbol is required")
    symbols = _load_symbols(market_type)
    if symbol not in symbols:
        # Offer near-misses so the model corrects instead of re-guessing.
        flat = symbol.replace("/", "").replace("-", "").replace("_", "").upper()
        hints = [s for s in symbols if s.replace("_", "") == flat][:5] or \
                [s for s in symbols if flat in s.replace("_", "")][:5]
        raise SafetyError(
            f"Symbol {symbol!r} does not exist on Pionex ({market_type}). "
            f"{'Did you mean: ' + ', '.join(hints) + '? ' if hints else ''}"
            f"Use list_symbols to see real symbols; the format is 'BASE_QUOTE' like 'BTC_USDT'."
        )
    if SETTINGS.symbol_whitelist and symbol not in SETTINGS.symbol_whitelist:
        raise SafetyError(
            f"Symbol {symbol!r} exists but is not in the operator-configured whitelist "
            f"{SETTINGS.symbol_whitelist}. This limit is set by the human operator and "
            f"cannot be overridden from the conversation."
        )
    return symbols[symbol]


# ---------------------------------------------------------------------------
# Hard numeric limits
# ---------------------------------------------------------------------------

def check_notional_cap(notional: float, context: str) -> None:
    require(
        notional > 0,
        f"{context}: notional must be a positive number, got {notional!r}.",
    )
    require(
        notional <= SETTINGS.max_order_notional,
        f"{context}: notional {notional:.2f} exceeds the operator-configured cap of "
        f"{SETTINGS.max_order_notional:.2f} (PIONEX_MCP_MAX_ORDER_NOTIONAL). "
        f"This cap cannot be raised from the conversation.",
    )


def check_price_deviation(symbol: str, price: float, market_type: str = "SPOT") -> float:
    """Reject LIMIT prices too far from the live mid-price. Returns the live
    reference price actually used."""
    from mcp_pionex.client import markets_client

    reference = markets_client().get_price(symbol, market_type=market_type)
    deviation_pct = abs(price - reference) / reference * 100.0
    require(
        deviation_pct <= SETTINGS.max_price_deviation_pct,
        f"LIMIT price {price} deviates {deviation_pct:.2f}% from the live mid-price "
        f"{reference} for {symbol}; the operator cap is "
        f"{SETTINGS.max_price_deviation_pct:.1f}%. Re-check the live price with "
        f"get_price before retrying — do not estimate prices from memory.",
    )
    return reference


# ---------------------------------------------------------------------------
# Two-phase commit (prepare -> confirm)
# ---------------------------------------------------------------------------

_PENDING: dict = {}  # token -> {"action", "params", "expires_at", "summary"}


def _params_fingerprint(action: str, params: dict) -> str:
    canon = json.dumps({"action": action, "params": params}, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode()).hexdigest()[:12]


def prepare_action(action: str, params: dict, summary: str) -> dict:
    """Store a fully-validated action and hand back a one-time token.

    The token embeds a fingerprint of the exact parameters, so the pending
    action can never drift from what was validated and shown to the user.
    """
    token = f"{_params_fingerprint(action, params)}-{secrets.token_hex(4)}"
    _PENDING[token] = {
        "action": action,
        "params": params,
        "summary": summary,
        "expires_at": time.monotonic() + SETTINGS.confirmation_ttl,
    }
    audit("prepare", action, {"token": token, "params": params})
    return {
        "confirmation_token": token,
        "action": action,
        "validated_params": params,
        "summary": summary,
        "expires_in_seconds": int(SETTINGS.confirmation_ttl),
        "next_step": (
            "Show this summary to the user. Only call confirm_action with this exact "
            "token after the user explicitly approves. The token is single-use and "
            "expires; the executed parameters are the ones stored server-side, "
            "never ones passed at confirm time."
        ),
    }


def take_pending(token: str) -> dict:
    entry = _PENDING.pop(token, None)
    require(
        entry is not None,
        f"Unknown or already-used confirmation token {token!r}. Tokens are single-use. "
        f"Prepare the action again to get a fresh token — never invent or reuse tokens.",
    )
    require(
        time.monotonic() <= entry["expires_at"],
        f"Confirmation token {token!r} expired "
        f"(TTL {int(SETTINGS.confirmation_ttl)}s). Prepare the action again; market "
        f"conditions may have changed.",
    )
    return entry


def pending_count() -> int:
    return len(_PENDING)


# ---------------------------------------------------------------------------
# Idempotency keys
# ---------------------------------------------------------------------------

def client_order_id(provided: str = "", prefix: str = "mcp") -> str:
    """Return a validated client-side order id, minting one when none is given.

    Every prepared order carries a clientOrderId so the operator can always
    reconcile what was sent (``get_order_by_client_id``) even if the
    confirm_action response is lost mid-flight. Server-minted ids look like
    ``mcp-1a2b3c4d5e6f`` and are unique per prepare call.
    """
    if provided:
        require(
            bool(_CLIENT_ID_RE.match(provided)),
            f"client_order_id {provided!r} is invalid: use 1-32 characters from "
            f"[A-Za-z0-9_-]. Leave it empty to let the server generate one.",
        )
        return provided
    return f"{prefix}-{secrets.token_hex(6)}"


# ---------------------------------------------------------------------------
# Provenance envelopes
# ---------------------------------------------------------------------------

def envelope(source: str, data, computed: bool = False, note: str = None) -> str:
    """Wrap a result with provenance so the model can cite where facts came
    from and must not report anything that is not inside ``data``."""
    body = {
        "ok": True,
        "source": source,
        "fetched_at": utc_now_iso(),
        "computed": computed,
        "data": data,
    }
    if note:
        body["note"] = note
    return json.dumps(body, default=str)


def error_envelope(exc: Exception) -> str:
    """Verbatim error passthrough — code and message exactly as received."""
    code = getattr(exc, "code", type(exc).__name__)
    message = getattr(exc, "message", str(exc))
    return json.dumps({
        "ok": False,
        "error_code": str(code),
        "error_message": str(message),
        "at": utc_now_iso(),
        "instruction": (
            "Report this error to the user verbatim. Do not speculate about causes "
            "that are not stated in the message."
        ),
    })


def guarded(source: str):
    """Decorator: run a tool body, wrap the result in a provenance envelope,
    and convert any exception into a verbatim error envelope."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                if isinstance(result, str):
                    return result  # already an envelope
                return envelope(source, result)
            except Exception as exc:  # SafetyError, REST_Exception, anything
                return error_envelope(exc)
        return inner
    return wrap


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def audit(event: str, action: str, detail: dict) -> None:
    try:
        os.makedirs(os.path.dirname(SETTINGS.audit_log), exist_ok=True)
        with open(SETTINGS.audit_log, "a") as fh:
            fh.write(json.dumps({
                "at": utc_now_iso(),
                "event": event,
                "action": action,
                "detail": detail,
            }, default=str) + "\n")
    except OSError:
        pass  # auditing must never break the trading path


# ---------------------------------------------------------------------------
# Capability gates
# ---------------------------------------------------------------------------

def require_credentials() -> None:
    require(
        SETTINGS.has_credentials,
        "This tool needs a Pionex API key. Set PIONEX_API_KEY and PIONEX_API_SECRET "
        "in the MCP server environment. Never ask the user to paste keys into the chat.",
    )


def require_trading() -> None:
    require_credentials()
    require(
        SETTINGS.trading_enabled,
        "Trading is DISABLED (read-only mode). The human operator must set "
        "PIONEX_MCP_TRADING_ENABLED=true in the server environment to enable it. "
        "This cannot be enabled from the conversation.",
    )


def require_bots() -> None:
    require_credentials()
    require(
        SETTINGS.bots_enabled,
        "Bot management is DISABLED. The operator must set PIONEX_MCP_BOTS_ENABLED=true "
        "in the server environment. This cannot be enabled from the conversation.",
    )


def require_futures() -> None:
    require_bots()
    require(
        SETTINGS.futures_enabled,
        "Futures grid bots are DISABLED. The operator must set "
        "PIONEX_MCP_FUTURES_ENABLED=true (in addition to PIONEX_MCP_BOTS_ENABLED) "
        "in the server environment. This cannot be enabled from the conversation.",
    )


def check_leverage(leverage: int) -> None:
    require(
        1 <= int(leverage) <= SETTINGS.max_leverage,
        f"leverage {leverage} is outside the operator-configured range "
        f"1..{SETTINGS.max_leverage} (PIONEX_MCP_MAX_LEVERAGE). "
        f"This cap cannot be raised from the conversation.",
    )


def require_earn() -> None:
    require_credentials()
    require(
        SETTINGS.earn_enabled,
        "Earn (Dual Investment) writes are DISABLED. The operator must set "
        "PIONEX_MCP_EARN_ENABLED=true in the server environment. "
        "This cannot be enabled from the conversation.",
    )

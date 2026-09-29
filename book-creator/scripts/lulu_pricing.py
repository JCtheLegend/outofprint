"""Price books from Lulu's own print cost.

A book sells for what Lulu charges us to print one copy plus a flat margin.
Lulu's cost depends on the product SKU (`pod_package_id`) and the interior's
page count, both of which the uploader already knows, so the price is worked
out here at upload time and stored on the `books` row alongside the cost it
came from:

  - `print_cost_cents` — Lulu's unit print cost, excluding tax and shipping.
    The storefront charges exactly this under a wholesale promo code.
  - `price_cents`      — `print_cost_cents + PRICE_MARGIN_CENTS`, the retail price.

Uses Lulu's cost-calculation endpoint, which only quotes — nothing is ordered.
It needs a shipping address to quote against; the print cost of a line item
does not depend on it, but the currency does, so we quote against a US one.

Needs LULU_CLIENT_KEY and LULU_CLIENT_SECRET (and optionally LULU_API_URL,
which defaults to production — sandbox prices are not real prices).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from decimal import ROUND_CEILING, Decimal

import fitz  # PyMuPDF

DEFAULT_API_URL = "https://api.lulu.com"
TOKEN_PATH = "/auth/realms/glasstree/protocol/openid-connect/token"

# The flat amount we add to Lulu's print cost for every book.
PRICE_MARGIN_CENTS = 1000

# Matches the storefront's fallback in website/src/lib/print.ts.
DEFAULT_POD_PACKAGE_ID = "0600X0900.BW.STD.PB.060UC444.MXX"

# Quoting needs an address; this one only decides the currency (USD).
QUOTE_ADDRESS = {
    "name": "Out of Print Press",
    "street1": "101 Independence Ave SE",
    "city": "Washington",
    "state_code": "DC",
    "country_code": "US",
    "postcode": "20540",
    "phone_number": "2025550100",
}

_token: str | None = None


class LuluPricingError(Exception):
    pass


def credentials_available() -> bool:
    return bool(os.environ.get("LULU_CLIENT_KEY") and os.environ.get("LULU_CLIENT_SECRET"))


def _api_url(path: str) -> str:
    return (os.environ.get("LULU_API_URL") or DEFAULT_API_URL).rstrip("/") + path


# Cloudflare in front of Lulu's API refuses Python's default urllib
# User-Agent outright (error 1010), so every request names itself.
USER_AGENT = "OutOfPrintPress-Uploader/1.0"


def _request(req: urllib.request.Request) -> dict:
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise LuluPricingError(f"Lulu {req.get_method()} {req.full_url} failed ({exc.code}): {body}") from exc


def _access_token() -> str:
    global _token
    if _token:
        return _token

    key = os.environ.get("LULU_CLIENT_KEY")
    secret = os.environ.get("LULU_CLIENT_SECRET")
    if not key or not secret:
        raise LuluPricingError("LULU_CLIENT_KEY and LULU_CLIENT_SECRET must be set to price books")

    basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
    req = urllib.request.Request(
        _api_url(TOKEN_PATH),
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    # One upload run is far shorter than the token's hour, so no refresh logic.
    _token = _request(req)["access_token"]
    return _token


def interior_page_count(interior_path) -> int:
    with fitz.open(interior_path) as doc:
        return doc.page_count


def _to_cents(amount: str) -> int:
    # Round any fraction of a cent up, so we never sell a hair under cost.
    return int((Decimal(str(amount)) * 100).to_integral_value(rounding=ROUND_CEILING))


def print_cost_cents(pod_package_id: str | None, page_count: int) -> int:
    """Lulu's cost to print one copy, in US cents, excluding tax and shipping."""
    body = {
        "line_items": [
            {
                "page_count": page_count,
                "pod_package_id": pod_package_id or DEFAULT_POD_PACKAGE_ID,
                "quantity": 1,
            }
        ],
        "shipping_address": QUOTE_ADDRESS,
        "shipping_option": "MAIL",
    }
    req = urllib.request.Request(
        _api_url("/print-job-cost-calculations/"),
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    quote = _request(req)

    currency = quote.get("currency")
    if currency and currency != "USD":
        raise LuluPricingError(f"Lulu quoted in {currency}, expected USD")

    try:
        return _to_cents(quote["line_item_costs"][0]["total_cost_excl_tax"])
    except (KeyError, IndexError) as exc:
        raise LuluPricingError(f"unexpected cost calculation response: {quote}") from exc


def price_book(pod_package_id: str | None, page_count: int) -> dict:
    """The pricing columns for a `books` row."""
    cost = print_cost_cents(pod_package_id, page_count)
    return {
        "page_count": page_count,
        "print_cost_cents": cost,
        "price_cents": cost + PRICE_MARGIN_CENTS,
    }

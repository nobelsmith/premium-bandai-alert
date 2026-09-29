"""Live contract tests against Premium Bandai.

These catch upstream site/API changes that would silently break alerts.
Skipped automatically when the network is unreachable unless --run-live is passed
via the live marker (default: run; use -m "not live" to skip).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from monitor import (
    API_URL,
    SERIES_PAGE_URL,
    USER_AGENT,
    catalog_params,
    fetch_all_products,
    fetch_via_api,
    fetch_via_html,
    is_available,
    parse_preload_products,
    parse_product,
)

REQUIRED_PRODUCT_KEYS = {
    "productCode",
    "productName",
    "saleStatus",
    "flags",
}
REQUIRED_PRICE_KEYS = {"amount", "currency"}


def _api_headers(area: str = "US") -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-G1-Area-Code": area,
        "Accept-Language": "en",
        "User-Agent": USER_AGENT,
        "Referer": f"https://p-bandai.com/{area.lower()}/series/onepiece-series",
    }


@pytest.fixture(scope="module")
def http_client():
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        yield client


@pytest.mark.live
class TestLiveApiContract:
    def test_search_endpoint_returns_expected_shape(self, http_client: httpx.Client):
        params = catalog_params("05-0004", "03-002", 0, 10)
        response = http_client.get(API_URL, params=params, headers=_api_headers())
        assert response.status_code == 200, (
            f"API returned {response.status_code}; Bandai may be blocking or down"
        )
        assert "application/json" in response.headers.get("content-type", "")

        data = response.json()
        assert "productResults" in data, (
            f"Missing productResults key; top-level keys={sorted(data.keys())}. "
            "API response shape may have changed."
        )
        result = data["productResults"]
        assert "totalCount" in result
        assert "products" in result
        assert isinstance(result["totalCount"], int)
        assert result["totalCount"] > 0, "Expected One Piece catalog to be non-empty"
        assert isinstance(result["products"], list)
        assert len(result["products"]) > 0

    def test_product_fields_still_parseable(self, http_client: httpx.Client):
        params = catalog_params("05-0004", "03-002", 0, 20)
        response = http_client.get(API_URL, params=params, headers=_api_headers())
        response.raise_for_status()
        products_raw: list[dict[str, Any]] = (
            response.json().get("productResults") or {}
        ).get("products") or []

        assert products_raw, "API returned zero products on first page"

        missing_keys: list[str] = []
        parse_failures: list[str] = []
        for raw in products_raw:
            absent = REQUIRED_PRODUCT_KEYS - set(raw.keys())
            if absent:
                missing_keys.append(f"{raw.get('productCode', '?')}: {sorted(absent)}")
            product = parse_product(raw)
            if product is None:
                parse_failures.append(str(raw.get("productCode")))
            else:
                # availability helper must accept live flag values
                is_available(product.sale_status, product.flags)

            price = raw.get("fixedListPrice") or raw.get("baseListPrice")
            if isinstance(price, dict):
                absent_price = REQUIRED_PRICE_KEYS - set(price.keys())
                assert not absent_price, (
                    f"Price object missing keys {absent_price} on {raw.get('productCode')}"
                )

        assert not missing_keys, (
            "Live products missing expected keys (schema change?):\n"
            + "\n".join(missing_keys)
        )
        assert not parse_failures, f"parse_product returned None for: {parse_failures}"

    def test_fetch_via_api_returns_full_catalog(self, http_client: httpx.Client):
        products = fetch_via_api(
            http_client, shop="05-0004", series="03-002", area="US", limit=50
        )
        assert len(products) >= 50, (
            f"Only got {len(products)} products; pagination or filters may be broken"
        )
        codes = [p.product_code for p in products]
        assert len(codes) == len(set(codes)), "Duplicate product codes in catalog fetch"


@pytest.mark.live
class TestLiveHtmlContract:
    def test_series_page_still_embeds_preload_data(self, http_client: httpx.Client):
        params = catalog_params("05-0004", "03-002", 0, 20)
        url = SERIES_PAGE_URL.format(area="us")
        response = http_client.get(
            url,
            params=params,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": USER_AGENT,
            },
        )
        assert response.status_code == 200
        assert "PRELOAD_DATA" in response.text, (
            "PRELOAD_DATA missing from series page HTML — HTML fallback will break"
        )
        products, total = parse_preload_products(response.text)
        assert total > 0
        assert len(products) > 0
        assert all(p.product_code for p in products)

    def test_html_fallback_fetch_works(self, http_client: httpx.Client):
        products = fetch_via_html(
            http_client, shop="05-0004", series="03-002", area="US", limit=20
        )
        assert len(products) > 0


@pytest.mark.live
class TestLiveEndToEndFetch:
    def test_fetch_all_products_succeeds(self, http_client: httpx.Client):
        products = fetch_all_products(http_client)
        assert len(products) > 0
        available = [p for p in products if p.available]
        # Informational: not a failure if zero — catalog can be fully sold out.
        print(
            f"\nLive catalog: {len(products)} products, "
            f"{len(available)} currently available"
        )

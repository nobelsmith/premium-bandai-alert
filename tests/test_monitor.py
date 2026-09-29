"""Unit tests for parsing, availability, diffs, state, and Discord embeds."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from monitor import (
    COLOR_AVAILABLE,
    COLOR_NEW,
    IMAGE_BASE,
    ITEM_URL,
    Alert,
    Product,
    diff_products,
    embed_for_alert,
    extract_json_object,
    fetch_via_api,
    fetch_via_html,
    format_price,
    image_url_from_product,
    is_available,
    load_state,
    parse_preload_products,
    parse_product,
    post_discord_alerts,
    save_state,
)


def _product(
    code: str,
    *,
    name: str = "Item",
    sale_status: str = "On",
    flags: tuple[str, ...] = (),
    available: bool | None = None,
    price: str | None = "USD 10.00",
) -> Product:
    if available is None:
        available = is_available(sale_status, flags)
    return Product(
        product_code=code,
        name=name,
        sale_status=sale_status,
        flags=flags,
        available=available,
        price=price,
        image_url=None,
    )


class TestIsAvailable:
    def test_on_without_blocking_flags(self):
        assert is_available("On", []) is True
        assert is_available("On", ["PRE_ORDER"]) is True

    def test_out_of_stock_blocks(self):
        assert is_available("On", ["OUT_OF_STOCK"]) is False

    def test_pre_order_closed_blocks(self):
        assert is_available("On", ["PRE_ORDER_CLOSED"]) is False

    def test_non_on_status_unavailable(self):
        assert is_available("Waiting", []) is False
        assert is_available("End", []) is False
        assert is_available("", ["PRE_ORDER"]) is False


class TestFormatPrice:
    def test_fixed_list_price(self):
        assert (
            format_price({"fixedListPrice": {"amount": 120.0, "currency": "USD"}})
            == "USD 120.00"
        )

    def test_falls_back_to_base_list_price(self):
        assert (
            format_price(
                {
                    "fixedListPrice": None,
                    "baseListPrice": {"amount": 99.5, "currency": "USD"},
                }
            )
            == "USD 99.50"
        )

    def test_missing_price(self):
        assert format_price({}) is None
        assert format_price({"fixedListPrice": "bad"}) is None

    def test_non_numeric_amount(self):
        assert (
            format_price({"fixedListPrice": {"amount": "n/a", "currency": "USD"}})
            == "USD n/a"
        )


class TestImageUrl:
    def test_relative_path(self):
        url = image_url_from_product(
            {"productImages": [{"fileUrl": "files/seller-products/x.jpg"}]}
        )
        assert url == IMAGE_BASE + "files/seller-products/x.jpg"

    def test_absolute_url(self):
        url = image_url_from_product(
            {"productImages": [{"fileUrl": "https://cdn.example.com/a.jpg"}]}
        )
        assert url == "https://cdn.example.com/a.jpg"

    def test_leading_slash_stripped(self):
        url = image_url_from_product({"productImages": [{"fileUrl": "/files/x.jpg"}]})
        assert url == IMAGE_BASE + "files/x.jpg"

    def test_empty(self):
        assert image_url_from_product({}) is None
        assert image_url_from_product({"productImages": []}) is None
        assert image_url_from_product({"productImages": [{"fileUrl": ""}]}) is None


class TestParseProduct:
    def test_parses_fixture_products(self, api_search_page: dict[str, Any]):
        raw_products = api_search_page["productResults"]["products"]
        products = [parse_product(p) for p in raw_products]
        assert products[0] is not None
        assert products[0].product_code == "TEST-AVAILABLE-001"
        assert products[0].available is True
        assert products[0].price == "USD 144.00"
        assert products[1] is not None and products[1].available is False
        assert products[2] is not None and products[2].available is False
        assert products[3] is not None and products[3].name == "Test Ended Item"
        assert products[3].price == "USD 99.50"

    def test_skips_missing_product_code(self):
        assert parse_product({"productName": {"en": "x"}, "saleStatus": "On"}) is None

    def test_falls_back_to_non_en_name(self):
        product = parse_product(
            {
                "productCode": "X",
                "productName": {"ja": "日本語名"},
                "saleStatus": "On",
                "flags": [],
            }
        )
        assert product is not None
        assert product.name == "日本語名"

    def test_falls_back_to_code_when_name_empty(self):
        product = parse_product(
            {"productCode": "CODE-1", "productName": {}, "saleStatus": "On", "flags": []}
        )
        assert product is not None
        assert product.name == "CODE-1"


class TestExtractJsonObject:
    def test_simple_object(self):
        text = 'prefix{"a": 1, "b": {"c": 2}}suffix'
        assert extract_json_object(text, 6) == {"a": 1, "b": {"c": 2}}

    def test_ignores_braces_inside_strings(self):
        text = '{"msg": "has { and } braces", "n": 1}'
        assert extract_json_object(text, 0) == {
            "msg": "has { and } braces",
            "n": 1,
        }

    def test_handles_escaped_quotes(self):
        text = r'{"msg": "say \"hi\"", "ok": true}'
        assert extract_json_object(text, 0) == {"msg": 'say "hi"', "ok": True}

    def test_rejects_non_object(self):
        with pytest.raises(ValueError, match="Expected JSON object"):
            extract_json_object("[1,2]", 0)

    def test_unbalanced(self):
        with pytest.raises(ValueError, match="Unbalanced"):
            extract_json_object('{"a": 1', 0)


class TestParsePreloadProducts:
    def test_parses_series_page(self, series_page_html: str):
        products, total = parse_preload_products(series_page_html)
        assert total == 2
        assert len(products) == 2
        assert products[0].product_code == "TEST-AVAILABLE-001"
        assert products[0].available is True

    def test_missing_preload_raises(self, series_page_no_preload_html: str):
        with pytest.raises(ValueError, match="PRELOAD_DATA not found"):
            parse_preload_products(series_page_no_preload_html)


class TestDiffProducts:
    def test_no_previous_means_seed_no_alerts(self):
        current = [_product("A", available=True)]
        assert diff_products(None, current) == []

    def test_new_unavailable_product(self):
        previous = {"OLD": {"available": False}}
        current = [
            _product("OLD", available=False),
            _product("NEW", sale_status="Waiting", available=False),
        ]
        alerts = diff_products(previous, current)
        assert len(alerts) == 1
        assert alerts[0].kind == "new"
        assert alerts[0].product.product_code == "NEW"

    def test_new_available_product_emits_both(self):
        previous = {}
        current = [_product("NEW", available=True)]
        alerts = diff_products(previous, current)
        assert [a.kind for a in alerts] == ["new", "available"]

    def test_became_available(self):
        previous = {"A": {"available": False, "saleStatus": "On", "flags": ["OUT_OF_STOCK"]}}
        current = [_product("A", available=True, flags=("PRE_ORDER",))]
        alerts = diff_products(previous, current)
        assert len(alerts) == 1
        assert alerts[0].kind == "available"

    def test_still_available_no_alert(self):
        previous = {"A": {"available": True}}
        current = [_product("A", available=True)]
        assert diff_products(previous, current) == []

    def test_became_unavailable_no_alert(self):
        previous = {"A": {"available": True}}
        current = [_product("A", available=False, flags=("OUT_OF_STOCK",))]
        assert diff_products(previous, current) == []

    def test_removed_products_ignored(self):
        previous = {"GONE": {"available": True}}
        assert diff_products(previous, []) == []


class TestState:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        path = tmp_path / "state.json"
        products = [
            _product("A", name="Alpha", available=True, flags=("PRE_ORDER",)),
            _product("B", name="Beta", sale_status="End", available=False),
        ]
        save_state(path, products)
        loaded = load_state(path)
        assert loaded == {
            "A": {
                "name": "Alpha",
                "saleStatus": "On",
                "flags": ["PRE_ORDER"],
                "available": True,
            },
            "B": {
                "name": "Beta",
                "saleStatus": "End",
                "flags": [],
                "available": False,
            },
        }

    def test_load_missing_returns_none(self, tmp_path: Path):
        assert load_state(tmp_path / "missing.json") is None

    def test_load_corrupt_raises(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Corrupt state file"):
            load_state(path)

    def test_load_non_object_raises(self, tmp_path: Path):
        path = tmp_path / "list.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(RuntimeError, match="must be a JSON object"):
            load_state(path)

    def test_save_is_atomic(self, tmp_path: Path):
        path = tmp_path / "state.json"
        save_state(path, [_product("X")])
        assert path.exists()
        assert not path.with_suffix(".json.tmp").exists()


class TestEmbeds:
    def test_new_product_embed(self):
        alert = diff_products({}, [_product("C1", name="Card", price="USD 12.00")])[0]
        embed = embed_for_alert(alert)
        assert embed["title"].startswith("New product:")
        assert embed["color"] == COLOR_NEW
        assert embed["url"] == ITEM_URL.format(code="C1")
        assert embed["footer"]["text"] == "C1"
        assert any(f["name"] == "Price" for f in embed["fields"])

    def test_available_embed(self):
        previous = {"C1": {"available": False}}
        current = [_product("C1", name="Card", available=True)]
        alert = diff_products(previous, current)[0]
        embed = embed_for_alert(alert)
        assert embed["title"].startswith("Available:")
        assert embed["color"] == COLOR_AVAILABLE

    def test_thumbnail_when_image_present(self):
        product = _product("C1")
        product = Product(
            product_code=product.product_code,
            name=product.name,
            sale_status=product.sale_status,
            flags=product.flags,
            available=True,
            price=product.price,
            image_url="https://example.com/x.jpg",
        )
        embed = embed_for_alert(Alert(kind="new", product=product))
        assert embed["thumbnail"]["url"] == "https://example.com/x.jpg"


class TestFetchViaApi:
    def test_paginates_until_exhausted(self, api_search_page: dict[str, Any]):
        page1 = {
            "productResults": {
                "totalCount": 3,
                "products": api_search_page["productResults"]["products"][:2],
            }
        }
        page2 = {
            "productResults": {
                "totalCount": 3,
                "products": api_search_page["productResults"]["products"][2:3],
            }
        }
        responses = [
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            idx = call_count["n"]
            call_count["n"] += 1
            return responses[idx]

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            products = fetch_via_api(
                client, shop="05-0004", series="03-002", area="US", limit=2
            )
        assert len(products) == 3
        assert call_count["n"] == 2

    def test_raises_after_retries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="error")

        transport = httpx.MockTransport(handler)
        with (
            patch("monitor.time.sleep"),
            httpx.Client(transport=transport) as client,
            pytest.raises(RuntimeError, match="API fetch failed"),
        ):
            fetch_via_api(
                client, shop="05-0004", series="03-002", area="US", limit=10
            )


class TestFetchViaHtml:
    def test_parses_html_pages(self, series_page_html: str):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=series_page_html)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            products = fetch_via_html(
                client, shop="05-0004", series="03-002", area="US", limit=100
            )
        assert len(products) == 2


class TestPostDiscordAlerts:
    def test_noop_when_empty(self):
        with patch("monitor.httpx.Client") as client_cls:
            post_discord_alerts("https://example.com/hook", [])
            client_cls.assert_not_called()

    def test_posts_embed_chunks(self):
        alerts = [Alert(kind="new", product=_product(f"P{i}")) for i in range(12)]

        posted: list[dict[str, Any]] = []

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(
            side_effect=lambda *a, **k: (posted.append(k["json"]), mock_response)[1]
        )

        with (
            patch("monitor.httpx.Client", return_value=mock_client),
            patch("monitor.time.sleep"),
        ):
            post_discord_alerts("https://example.com/hook", alerts)

        assert len(posted) == 2
        assert len(posted[0]["embeds"]) == 10
        assert len(posted[1]["embeds"]) == 2

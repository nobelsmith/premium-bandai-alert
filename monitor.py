#!/usr/bin/env python3
"""Premium Bandai US catalog monitor — Discord webhook alerts."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

API_URL = "https://p-bandai.com/api/search"
SERIES_PAGE_URL = "https://p-bandai.com/{area}/series/onepiece-series"
ITEM_URL = "https://p-bandai.com/us/item/{code}"
IMAGE_BASE = "https://p-bandai.com/"
UNAVAILABLE_FLAGS = frozenset({"OUT_OF_STOCK", "PRE_ORDER_CLOSED"})
MAX_EMBEDS_PER_MESSAGE = 10
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

COLOR_NEW = 0x3498DB  # blue
COLOR_AVAILABLE = 0x2ECC71  # green

PRELOAD_RE = re.compile(r"PRELOAD_DATA\s*=\s*")


@dataclass(frozen=True)
class Product:
    product_code: str
    name: str
    sale_status: str
    flags: tuple[str, ...]
    available: bool
    price: str | None
    image_url: str | None

    def to_state(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "saleStatus": self.sale_status,
            "flags": list(self.flags),
            "available": self.available,
        }


@dataclass(frozen=True)
class Alert:
    kind: str  # "new" | "available"
    product: Product


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value


def is_available(sale_status: str, flags: list[str] | tuple[str, ...]) -> bool:
    if sale_status != "On":
        return False
    return not any(flag in UNAVAILABLE_FLAGS for flag in flags)


def format_price(product: dict[str, Any]) -> str | None:
    price = product.get("fixedListPrice") or product.get("baseListPrice")
    if not isinstance(price, dict):
        return None
    amount = price.get("amount")
    currency = price.get("currency") or "USD"
    if amount is None:
        return None
    try:
        return f"{currency} {float(amount):.2f}"
    except (TypeError, ValueError):
        return f"{currency} {amount}"


def image_url_from_product(product: dict[str, Any]) -> str | None:
    images = product.get("productImages") or []
    if not images:
        return None
    file_url = images[0].get("fileUrl")
    if not file_url:
        return None
    if file_url.startswith("http"):
        return file_url
    return IMAGE_BASE + file_url.lstrip("/")


def parse_product(raw: dict[str, Any]) -> Product | None:
    code = raw.get("productCode")
    if not code:
        return None
    name_obj = raw.get("productName") or {}
    name = name_obj.get("en") or next(
        (v for v in name_obj.values() if v), code
    )
    sale_status = raw.get("saleStatus") or ""
    flags = tuple(raw.get("flags") or [])
    return Product(
        product_code=code,
        name=name,
        sale_status=sale_status,
        flags=flags,
        available=is_available(sale_status, flags),
        price=format_price(raw),
        image_url=image_url_from_product(raw),
    )


def extract_json_object(text: str, start: int) -> dict[str, Any]:
    """Parse a JSON object starting at text[start] (must be '{')."""
    if start >= len(text) or text[start] != "{":
        raise ValueError("Expected JSON object")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("Unbalanced JSON object")


def parse_preload_products(html: str) -> tuple[list[Product], int]:
    match = PRELOAD_RE.search(html)
    if not match:
        raise ValueError("PRELOAD_DATA not found in page HTML")
    data = extract_json_object(html, match.end())
    result = (data.get("searchResult") or {}).get("productResults") or {}
    total = int(result.get("totalCount") or 0)
    products: list[Product] = []
    for raw in result.get("products") or []:
        product = parse_product(raw)
        if product:
            products.append(product)
    return products, total


def catalog_params(shop: str, series: str, offset: int, limit: int) -> dict[str, Any]:
    return {
        "_f_shops": shop,
        "_f_series": series,
        "offset": offset,
        "limit": limit,
        "sortType": "NewArrival",
    }


def fetch_via_api(
    client: httpx.Client,
    *,
    shop: str,
    series: str,
    area: str,
    limit: int,
) -> list[Product]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "X-G1-Area-Code": area,
        "Accept-Language": "en",
        "User-Agent": USER_AGENT,
        "Referer": f"https://p-bandai.com/{area.lower()}/series/onepiece-series",
    }

    products: list[Product] = []
    offset = 0
    total: int | None = None
    max_retries = 3

    while total is None or offset < total:
        params = catalog_params(shop, series, offset, limit)
        last_error: Exception | None = None
        data: dict[str, Any] | None = None
        for attempt in range(max_retries):
            try:
                response = client.get(
                    API_URL, params=params, headers=headers, timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                break
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
        if data is None:
            raise RuntimeError(f"API fetch failed at offset={offset}: {last_error}")

        result = data.get("productResults") or {}
        if total is None:
            total = int(result.get("totalCount") or 0)
        page = result.get("products") or []
        if not page:
            break
        for raw in page:
            product = parse_product(raw)
            if product:
                products.append(product)
        offset += len(page)
        if len(page) < limit:
            break

    return products


def fetch_via_html(
    client: httpx.Client,
    *,
    shop: str,
    series: str,
    area: str,
    limit: int,
) -> list[Product]:
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": USER_AGENT,
    }
    page_url = SERIES_PAGE_URL.format(area=area.lower())
    products: list[Product] = []
    offset = 0
    total: int | None = None
    max_retries = 3

    while total is None or offset < total:
        params = catalog_params(shop, series, offset, limit)
        last_error: Exception | None = None
        page_products: list[Product] | None = None
        for attempt in range(max_retries):
            try:
                response = client.get(
                    page_url, params=params, headers=headers, timeout=30.0
                )
                response.raise_for_status()
                page_products, page_total = parse_preload_products(response.text)
                if total is None:
                    total = page_total
                break
            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    time.sleep(2**attempt)
        if page_products is None:
            raise RuntimeError(f"HTML fetch failed at offset={offset}: {last_error}")
        if not page_products:
            break
        products.extend(page_products)
        offset += len(page_products)
        if len(page_products) < limit:
            break

    return products


def fetch_all_products(client: httpx.Client) -> list[Product]:
    shop = env("BANDAI_SHOP", "05-0004") or "05-0004"
    series = env("BANDAI_SERIES", "03-002") or "03-002"
    area = env("BANDAI_AREA", "US") or "US"
    limit = int(env("BANDAI_PAGE_LIMIT", "100") or "100")

    try:
        products = fetch_via_api(
            client, shop=shop, series=series, area=area, limit=limit
        )
        print(f"Fetched {len(products)} products via API")
        return products
    except RuntimeError as api_error:
        print(f"API path failed ({api_error}); falling back to HTML", file=sys.stderr)
        products = fetch_via_html(
            client, shop=shop, series=series, area=area, limit=limit
        )
        print(f"Fetched {len(products)} products via HTML")
        return products


def load_state(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Corrupt state file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"State file {path} must be a JSON object")
    return data


def save_state(path: Path, products: list[Product]) -> None:
    snapshot = {p.product_code: p.to_state() for p in products}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def diff_products(
    previous: dict[str, Any] | None, current: list[Product]
) -> list[Alert]:
    if previous is None:
        return []

    alerts: list[Alert] = []
    for product in current:
        prior = previous.get(product.product_code)
        if prior is None:
            alerts.append(Alert(kind="new", product=product))
            if product.available:
                alerts.append(Alert(kind="available", product=product))
            continue
        was_available = bool(prior.get("available"))
        if product.available and not was_available:
            alerts.append(Alert(kind="available", product=product))
    return alerts


def embed_for_alert(alert: Alert) -> dict[str, Any]:
    product = alert.product
    if alert.kind == "available":
        title_prefix = "Available"
        color = COLOR_AVAILABLE
    else:
        title_prefix = "New product"
        color = COLOR_NEW

    fields = [
        {"name": "Status", "value": product.sale_status or "—", "inline": True},
        {
            "name": "Flags",
            "value": ", ".join(product.flags) if product.flags else "None",
            "inline": True,
        },
    ]
    if product.price:
        fields.insert(0, {"name": "Price", "value": product.price, "inline": True})

    embed: dict[str, Any] = {
        "title": f"{title_prefix}: {product.name}",
        "url": ITEM_URL.format(code=product.product_code),
        "color": color,
        "fields": fields,
        "footer": {"text": product.product_code},
    }
    if product.image_url:
        embed["thumbnail"] = {"url": product.image_url}
    return embed


def post_discord_alerts(webhook_url: str, alerts: list[Alert]) -> None:
    if not alerts:
        return

    embeds = [embed_for_alert(a) for a in alerts]
    with httpx.Client() as client:
        for i in range(0, len(embeds), MAX_EMBEDS_PER_MESSAGE):
            chunk = embeds[i : i + MAX_EMBEDS_PER_MESSAGE]
            response = client.post(
                webhook_url,
                json={"embeds": chunk},
                timeout=30.0,
            )
            response.raise_for_status()
            if i + MAX_EMBEDS_PER_MESSAGE < len(embeds):
                time.sleep(1)


def main() -> int:
    webhook = env("DISCORD_WEBHOOK_URL")
    if not webhook:
        print(
            "DISCORD_WEBHOOK_URL is missing or empty. "
            "Add a repository secret named exactly DISCORD_WEBHOOK_URL "
            "(Settings → Secrets and variables → Actions).",
            file=sys.stderr,
        )
        return 1

    state_path = Path(env("STATE_PATH", "state.json") or "state.json")

    try:
        previous = load_state(state_path)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        with httpx.Client(follow_redirects=True) as client:
            products = fetch_all_products(client)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not products:
        print("No products returned; leaving state unchanged", file=sys.stderr)
        return 1

    seeded = previous is None
    alerts = diff_products(previous, products)

    if seeded:
        print(f"Seeded baseline with {len(products)} products (no alerts)")
    else:
        print(
            f"Checked {len(products)} products; "
            f"{len(alerts)} alert(s) "
            f"({sum(1 for a in alerts if a.kind == 'new')} new, "
            f"{sum(1 for a in alerts if a.kind == 'available')} available)"
        )

    try:
        if not seeded and alerts:
            post_discord_alerts(webhook, alerts)
        save_state(state_path, products)
    except httpx.HTTPError as exc:
        print(f"Discord webhook failed; state not updated: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Failed to save state: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Flux produits des plateformes e-commerce courantes (Shopify, WooCommerce).

Beaucoup de boutiques tournent sur ces solutions, qui exposent publiquement
leur catalogue en JSON : bien plus rapide et fiable que lire les pages une à une.
"""
from __future__ import annotations

from ..models import Listing


def parse_shopify(data: dict, domain: str, source: str, currency: str = "EUR") -> list[Listing]:
    out = []
    for p in data.get("products", []):
        images = p.get("images") or []
        image = images[0].get("src", "") if images else ""
        for v in p.get("variants", []):
            if v.get("available") is False:
                continue
            try:
                price = float(v["price"])
            except (KeyError, TypeError, ValueError):
                continue
            title = p.get("title", "")
            if v.get("title") and v["title"] != "Default Title":
                title += f" - {v['title']}"
            barcode = "".join(c for c in str(v.get("barcode") or "") if c.isdigit())
            out.append(Listing(
                source=source, item_id=str(v.get("id")), title=title, price=price,
                currency=currency, image=image,
                url=f"https://{domain}/products/{p.get('handle')}?variant={v.get('id')}",
                gtin=barcode if 8 <= len(barcode) <= 14 else "",
            ))
    return out


def parse_woocommerce(data: list, source: str) -> list[Listing]:
    out = []
    for p in data if isinstance(data, list) else []:
        if p.get("is_in_stock") is False:
            continue
        prices = p.get("prices") or {}
        try:
            price = int(prices["price"]) / 10 ** int(prices.get("currency_minor_unit", 2))
        except (KeyError, TypeError, ValueError):
            continue
        images = p.get("images") or []
        out.append(Listing(
            source=source, item_id=str(p.get("id")), title=p.get("name", ""), price=price,
            currency=prices.get("currency_code", "EUR"), url=p.get("permalink", ""),
            image=images[0].get("src", "") if images else "",
        ))
    return out

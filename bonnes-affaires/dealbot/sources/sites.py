from __future__ import annotations

import json
import re
import urllib.parse
from html.parser import HTMLParser

from ..config import Watch
from ..http import HttpError, Session
from ..models import Listing
from .base import Source


class SitesSource(Source):
    """Surveille n'importe quelle page produit ou page catégorie d'un site marchand.

    La grande majorité des boutiques (Fnac, Darty, Cdiscount, Boulanger, Decathlon,
    les boutiques Shopify/WooCommerce/PrestaShop…) publient leurs prix en données
    structurées schema.org (JSON-LD) pour Google. On lit ces données : pas besoin
    d'écrire un scraper par site. Les erreurs de prix se repèrent ensuite par une
    chute brutale du prix d'un même produit, ou en dessous du prix de référence.
    """

    name = "sites"

    def __init__(self, session: Session):
        self.session = session

    def search(self, watch: Watch) -> list[Listing]:
        listings: list[Listing] = []
        for url in watch.urls:
            try:
                page = self.session.request(url)
            except HttpError as e:
                print(f"[sites] {url} : {e}")
                continue
            listings += extract_listings(page, url)
        return listings


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content") is not None:
                self.meta.setdefault(key.lower(), a["content"])

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.blocks.append("".join(self._buf))
            self._in_ld = False


def parse_price(value) -> float | None:
    """'1 299,99 €', '1,299.99', 1299.99 -> 1299.99"""
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    s = re.sub(r"[^\d,.]", "", value)
    if not s:
        return None
    if "," in s and "." in s:
        # Le dernier séparateur est le séparateur décimal.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 and head else head.replace(",", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def _walk(node):
    """Parcourt récursivement le JSON-LD (gère @graph, listes, ItemList…)."""
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "itemListElement", "item", "mainEntity", "hasVariant"):
            if k in node:
                yield from _walk(node[k])


def _types(node: dict) -> set[str]:
    t = node.get("@type", [])
    return {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}


def _offer(offers) -> tuple[float, str, bool] | None:
    """Renvoie (prix, devise, en_stock) de la meilleure offre disponible."""
    best = None
    for o in offers if isinstance(offers, list) else [offers]:
        if not isinstance(o, dict):
            continue
        price = parse_price(o.get("price"))
        if price is None:
            price = parse_price(o.get("lowPrice"))
        if price is None and isinstance(o.get("priceSpecification"), dict):
            price = parse_price(o["priceSpecification"].get("price"))
        if price is None or price <= 0:
            continue
        availability = str(o.get("availability", "")).lower()
        in_stock = not any(w in availability for w in ("outofstock", "soldout", "discontinued"))
        cand = (price, o.get("priceCurrency") or "EUR", in_stock)
        if best is None or (in_stock, -price) > (best[2], -best[0]):
            best = cand
    return best


def extract_listings(page: str, page_url: str) -> list[Listing]:
    parser = _Collector()
    parser.feed(page)
    host = urllib.parse.urlparse(page_url).netloc.removeprefix("www.")
    found: dict[str, Listing] = {}

    for raw in parser.blocks:
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if "product" not in _types(node) or "offers" not in node:
                continue
            offer = _offer(node["offers"])
            if not offer or not offer[2]:  # rupture de stock : prix non achetable
                continue
            price, currency, _ = offer
            url = urllib.parse.urljoin(page_url, node.get("url") or page_url)
            item_id = str(node.get("sku") or node.get("gtin13") or node.get("productID") or url)
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            found.setdefault(item_id, Listing(
                source=f"site:{host}", item_id=item_id, title=str(node.get("name", "")).strip(),
                price=price, currency=currency, url=url, image=str(image or ""),
            ))

    # Repli : balises meta Open Graph (pages produit sans JSON-LD).
    if not found:
        price = parse_price(parser.meta.get("product:price:amount") or parser.meta.get("og:price:amount"))
        title = parser.meta.get("og:title", "")
        if price and title:
            found[page_url] = Listing(
                source=f"site:{host}", item_id=page_url, title=title, price=price,
                currency=(parser.meta.get("product:price:currency")
                          or parser.meta.get("og:price:currency") or "EUR"),
                url=page_url, image=parser.meta.get("og:image", ""),
            )
    return list(found.values())

from __future__ import annotations

import json
import re
import urllib.parse
from html.parser import HTMLParser

from ..config import Watch
from ..http import HttpError, Session
from ..models import Listing
from ..textutil import normalize
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
        self.itemprops: dict[str, list[str]] = {}  # microdonnées schema.org
        self.links: list[str] = []
        self.title = ""
        self._in_ld = self._in_title = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self._in_ld, self._buf = True, []
        elif tag == "title":
            self._in_title = True
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content") is not None:
                self.meta.setdefault(key.lower(), a["content"])
        prop = a.get("itemprop")
        if prop and a.get("content") is not None:
            self.itemprops.setdefault(prop.lower(), []).append(a["content"])

    def handle_data(self, data):
        if self._in_ld:
            self._buf.append(data)
        elif self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self.blocks.append("".join(self._buf))
            self._in_ld = False
        elif tag == "title":
            self._in_title = False


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


def _seller_name(offer: dict) -> str:
    seller = offer.get("seller") or offer.get("offeredBy") or ""
    if isinstance(seller, list):
        seller = seller[0] if seller else ""
    if isinstance(seller, dict):
        seller = seller.get("name", "")
    return str(seller).strip()


def seller_allowed(seller: str, allowed: list[str]) -> bool:
    if not allowed or not seller:
        return True  # pas de filtre, ou vendeur non publié par le site
    s = normalize(seller)
    return any(normalize(a) in s for a in allowed)


def _offer(offers, sellers: list[str] | None = None) -> tuple[float, str, bool, str] | None:
    """Renvoie (prix, devise, en_stock, vendeur) de la meilleure offre acceptable."""
    best = None
    for o in offers if isinstance(offers, list) else [offers]:
        if not isinstance(o, dict):
            continue
        if o.get("@type") == "AggregateOffer" and isinstance(o.get("offers"), list) and sellers:
            # Le détail des offres permet de filtrer les revendeurs.
            sub = _offer(o["offers"], sellers)
            if sub and (best is None or (sub[2], -sub[0]) > (best[2], -best[0])):
                best = sub
            continue
        seller = _seller_name(o)
        if not seller_allowed(seller, sellers or []):
            continue  # revendeur tiers non autorisé sur cette marketplace
        price = parse_price(o.get("price"))
        if price is None:
            price = parse_price(o.get("lowPrice"))
        if price is None and isinstance(o.get("priceSpecification"), dict):
            price = parse_price(o["priceSpecification"].get("price"))
        if price is None or price <= 0:
            continue
        availability = str(o.get("availability", "")).lower()
        in_stock = not any(w in availability for w in ("outofstock", "soldout", "discontinued"))
        cand = (price, o.get("priceCurrency") or "EUR", in_stock, seller)
        if best is None or (in_stock, -price) > (best[2], -best[0]):
            best = cand
    return best


def _gtin(node: dict) -> str:
    for k in ("gtin13", "gtin", "gtin12", "gtin14", "gtin8", "ean", "isbn"):
        v = re.sub(r"\D", "", str(node.get(k) or ""))
        if 8 <= len(v) <= 14:
            return v.zfill(13) if len(v) == 12 else v  # UPC-A -> EAN-13
    return ""


def extract_listings(page: str, page_url: str, sellers: list[str] | None = None,
                     source: str = "") -> list[Listing]:
    return parse_page(page, page_url, sellers, source)[0]


def parse_page(page: str, page_url: str, sellers: list[str] | None = None,
               source: str = "") -> tuple[list[Listing], list[str]]:
    """Renvoie (produits trouvés, liens de la page en adresses complètes)."""
    parser = _Collector()
    try:
        parser.feed(page)
    except Exception:  # HTML très cassé : on garde ce qui a pu être lu
        pass
    links = []
    for href in parser.links:
        href = href.strip()
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        links.append(urllib.parse.urljoin(page_url, href).split("#", 1)[0])
    host = urllib.parse.urlparse(page_url).netloc.removeprefix("www.")
    source = source or f"site:{host}"
    found: dict[str, Listing] = {}
    saw_product = False

    for raw in parser.blocks:
        try:
            data = json.loads(raw.strip(), strict=False)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if "product" not in _types(node) or "offers" not in node:
                continue
            saw_product = True
            offer = _offer(node["offers"], sellers)
            if not offer or not offer[2]:  # rupture de stock : prix non achetable
                continue
            price, currency, _, seller = offer
            url = urllib.parse.urljoin(page_url, node.get("url") or page_url)
            gtin = _gtin(node)
            item_id = str(node.get("sku") or gtin or node.get("productID") or url)
            image = node.get("image")
            if isinstance(image, list):
                image = image[0] if image else ""
            if isinstance(image, dict):
                image = image.get("url", "")
            found.setdefault(item_id, Listing(
                source=source, item_id=item_id, title=str(node.get("name", "")).strip(),
                price=price, currency=currency, url=url, image=str(image or ""),
                gtin=gtin, seller=seller, seller_checked=bool(seller and sellers),
            ))

    # Repli : balises Open Graph ou microdonnées (pages produit sans JSON-LD).
    # Jamais sur une marketplace filtrée : on ne saurait pas qui vend.
    if not saw_product and not sellers:
        props = parser.itemprops
        price = parse_price(parser.meta.get("product:price:amount") or parser.meta.get("og:price:amount"))
        # Un seul prix en microdonnées = une fiche produit (plusieurs = page liste).
        if price is None and len(set(props.get("price", []))) == 1:
            price = parse_price(props["price"][0])
        title = (parser.meta.get("og:title") or (props.get("name") or [""])[0]
                 or parser.title).strip()
        if price and title:
            gtin = next((re.sub(r"\D", "", v[0]) for k, v in props.items()
                         if k in ("gtin13", "gtin", "gtin12", "gtin14", "gtin8", "ean")), "")
            found[page_url] = Listing(
                source=source, item_id=page_url, title=title, price=price,
                currency=(parser.meta.get("product:price:currency")
                          or parser.meta.get("og:price:currency")
                          or (props.get("pricecurrency") or ["EUR"])[0]),
                url=page_url, image=parser.meta.get("og:image", ""),
                gtin=gtin if 8 <= len(gtin) <= 14 else "",
            )
    return list(found.values()), links

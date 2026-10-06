"""Lecture des plans de site (sitemap.xml) pour lister toutes les pages produit."""
from __future__ import annotations

import gzip
import re
import xml.etree.ElementTree as ET

# Sous-sitemaps qui contiennent généralement les fiches produit.
# (pas de lettre juste avant : « sitemap » contient « item »)
PRODUCT_HINT = re.compile(r"(?<![a-z])(produ|article|items?\b|pdp|fiche|catalog|offer|sku)", re.I)
NOT_PRODUCT_HINT = re.compile(r"(?<![a-z])(blog|news|actu|magazine|conseil|guide|store|magasin|"
                              r"image|video|brand|marque|static|page-|cms|faq)", re.I)
SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|pdf|svg|mp4)(\?|$)", re.I)


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(raw: bytes) -> tuple[str, list[tuple[str, str]]]:
    """Renvoie ("index" | "urlset", [(url, lastmod), ...])."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    root = ET.fromstring(raw)
    kind = "index" if _strip_ns(root.tag) == "sitemapindex" else "urlset"
    entries = []
    for node in root:
        loc = lastmod = ""
        for child in node:
            tag = _strip_ns(child.tag)
            if tag == "loc":
                loc = (child.text or "").strip()
            elif tag == "lastmod":
                lastmod = (child.text or "").strip()
        if loc:
            entries.append((loc, lastmod))
    return kind, entries


def pick_children(children: list[tuple[str, str]], path_prefix: str = "") -> list[tuple[str, str]]:
    """Dans un index, garde les sous-sitemaps produits s'ils sont identifiables."""
    if path_prefix:
        lang = path_prefix.strip("/").split("/")[0].lower()
        localized = [c for c in children if lang in c[0].lower()]
        children = localized or children
    products = [c for c in children if PRODUCT_HINT.search(c[0].rsplit("/", 1)[-1])]
    if products:
        return products
    return [c for c in children if not NOT_PRODUCT_HINT.search(c[0].rsplit("/", 1)[-1])] or children


def keep_url(url: str, domain: str, path_prefix: str = "") -> bool:
    if SKIP_EXT.search(url):
        return False
    m = re.match(r"https?://([^/]+)(/[^?#]*)?", url)
    bare = lambda d: d.lower().removeprefix("www.")
    if not m or bare(m.group(1)) != bare(domain):
        return False
    return not path_prefix or (m.group(2) or "/").startswith(path_prefix)

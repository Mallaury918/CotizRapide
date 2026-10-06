"""Scan d'un site (exécuté dans un thread : aucun accès à la base ici)."""
from __future__ import annotations

import json
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..config import Site
from ..http import HttpError, Session
from ..models import Listing
from ..sources.sites import extract_listings
from . import feeds, sitemap

SITEMAP_REFRESH = 24 * 3600
MAX_SITEMAP_FILES = 60
MAX_PAGES_KNOWN = 300_000
BLOCK_STATUSES = {401, 403, 429, 503}


@dataclass
class SiteState:
    mode: str = ""  # "shopify", "woocommerce", "sitemap"
    cursor: int = 1  # page suivante pour les flux paginés
    sitemap_at: float = 0.0


@dataclass
class SiteResult:
    site: Site
    mode: str = ""
    cursor: int = 1
    listings: list[Listing] = field(default_factory=list)
    checked: dict[str, bool] = field(default_factory=dict)  # url -> page produit ?
    pages: list[tuple[str, str]] | None = None  # sitemap rafraîchi : (url, lastmod)
    error: str = ""
    blocked: bool = False
    requests: int = 0


def source_name(site: Site) -> str:
    return "site:" + site.domain.lower().removeprefix("www.")


class Crawler:
    def __init__(self, site: Site, state: SiteState, budget: int, session: Session | None = None):
        self.site = site
        self.state = state
        self.budget = budget
        self.session = session or Session(min_delay=1.5)
        self.base = f"https://{site.domain}"
        self.source = source_name(site)
        self.result = SiteResult(site=site, mode=state.mode, cursor=state.cursor)
        self.robots = urllib.robotparser.RobotFileParser()
        self._blocked_hits = 0

    # -- utilitaires ---------------------------------------------------------
    def _get(self, url: str, binary: bool = False, counted: bool = True, **kw):
        if counted:
            if self.result.requests >= self.budget:
                raise _BudgetExhausted
            self.result.requests += 1
        try:
            out = self.session.request_bytes(url, **kw) if binary else self.session.request(url, **kw)
            self._blocked_hits = 0
            return out
        except HttpError as e:
            if e.status in BLOCK_STATUSES:
                self._blocked_hits += 1
                if self._blocked_hits >= 3:
                    self.result.blocked = True
                    raise _Blocked(f"HTTP {e.status} répétés (protection anti-robots)") from None
            raise

    def _allowed(self, url: str) -> bool:
        return self.robots.can_fetch("*", url)

    # -- étapes --------------------------------------------------------------
    def _load_robots(self) -> list[str]:
        try:
            txt = self._get(self.base + "/robots.txt", counted=False)
        except HttpError as e:
            if e.status in BLOCK_STATUSES:
                raise _Blocked(f"robots.txt refusé (HTTP {e.status})") from None
            txt = ""  # pas de robots.txt : tout est permis
        self.robots.parse(txt.splitlines())
        return list(self.robots.site_maps() or [])

    def _detect_mode(self) -> str:
        probes = [("shopify", "/products.json", {"limit": 1}, lambda d: isinstance(d, dict) and "products" in d),
                  ("woocommerce", "/wp-json/wc/store/v1/products", {"per_page": 1},
                   lambda d: isinstance(d, list))]
        mode = "sitemap"
        for name, path, params, ok in probes:
            if not self._allowed(self.base + path):
                continue
            try:
                if ok(json.loads(self._get(self.base + path, params=params))):
                    mode = name
                    break
            except (HttpError, ValueError):
                pass
        self._blocked_hits = 0  # un 403 sur une sonde n'est pas un blocage du site
        return mode

    def _crawl_feed(self) -> None:
        shopify = self.result.mode == "shopify"
        url = self.base + ("/products.json" if shopify else "/wp-json/wc/store/v1/products")
        page = self.state.cursor
        while True:
            params = {"limit": 250, "page": page} if shopify else {"per_page": 100, "page": page}
            data = json.loads(self._get(url, params=params))
            items = (feeds.parse_shopify(data, self.site.domain, self.source) if shopify
                     else feeds.parse_woocommerce(data, self.source))
            raw_count = len(data.get("products", [])) if shopify else len(data)
            self.result.listings += items
            if raw_count == 0:
                page = 1  # fin du catalogue : on recommence au début au prochain tour
                break
            page += 1
            self.result.cursor = page
        self.result.cursor = page

    def _refresh_sitemap(self, declared: list[str]) -> None:
        roots = declared or [self.base + "/sitemap.xml"]
        queue = [(u, "") for u in roots]
        pages: dict[str, str] = {}
        files = 0
        while queue and files < MAX_SITEMAP_FILES and len(pages) < MAX_PAGES_KNOWN:
            url, _ = queue.pop(0)
            files += 1
            try:
                # Les fichiers sitemap ne comptent pas dans le quota de pages produit.
                kind, entries = sitemap.parse(self._get(url, binary=True, counted=False))
            except (HttpError, ValueError, OSError, EOFError, ET.ParseError):
                continue  # sitemap absent, XML invalide, gzip cassé…
            if kind == "index":
                queue += sitemap.pick_children(entries, self.site.path_prefix)
            else:
                for loc, lastmod in entries:
                    if sitemap.keep_url(loc, self.site.domain, self.site.path_prefix) \
                            and self._allowed(loc):
                        pages[loc] = lastmod
        if pages:
            self.result.pages = sorted(pages.items(), key=lambda kv: kv[1], reverse=True)

    def _check_pages(self, urls: list[str]) -> None:
        for url in urls:
            if not self._allowed(url):
                self.result.checked[url] = False
                continue
            try:
                html = self._get(url)
            except HttpError:
                continue
            found = extract_listings(html, url, self.site.sellers, self.source)
            self.result.checked[url] = bool(found)
            self.result.listings += found

    def run(self, to_check: list[str]) -> SiteResult:
        try:
            declared = self._load_robots()
            if not self.result.mode:
                self.result.mode = self._detect_mode()
            if self.result.mode in ("shopify", "woocommerce"):
                self._crawl_feed()
            else:
                self._check_pages([u for u in self.site.start_urls])
                if time.time() - self.state.sitemap_at > SITEMAP_REFRESH:
                    self._refresh_sitemap(declared)
                    if not to_check and self.result.pages:
                        to_check = [u for u, _ in self.result.pages]
                self._check_pages(to_check)
        except _BudgetExhausted:
            pass
        except _Blocked as e:
            self.result.blocked = True
            self.result.error = str(e)
        except Exception as e:  # site en panne, format inattendu…
            self.result.error = f"{type(e).__name__}: {e}"
        return self.result


class _BudgetExhausted(Exception):
    pass


class _Blocked(Exception):
    pass

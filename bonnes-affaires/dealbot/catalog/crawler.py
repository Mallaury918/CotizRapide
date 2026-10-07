"""Scan d'un site (exécuté dans un thread : aucun accès à la base ici)."""
from __future__ import annotations

import json
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from ..config import Site
from ..http import HttpError, Session
from ..models import Listing
from ..sources.sites import parse_page
from . import feeds, sitemap

SITEMAP_REFRESH = 24 * 3600
MAX_SITEMAP_FILES = 60
MAX_PAGES_KNOWN = 300_000
BLOCK_STATUSES = {401, 403, 429, 503}
# Pages de vérification renvoyées par les protections anti-robots (souvent en
# HTTP 200, à la place de la vraie page) : (motif, nom de la protection).
# Uniquement des motifs propres aux pages de vérification : les sites protégés
# chargent aussi le script anti-robot sur leurs pages normales.
CHALLENGES = [
    (re.compile(r"captcha-delivery\.com", re.I), "DataDome"),
    (re.compile(r"_cf_chl_opt|<title>Just a moment\.\.\.</title>|Attention Required! \| Cloudflare", re.I),
     "Cloudflare"),
    (re.compile(r"px-captcha", re.I), "PerimeterX"),
    (re.compile(r"Incapsula incident ID", re.I), "Imperva"),
    (re.compile(r"<title>Access Denied</title>", re.I), "Akamai"),
]
MAX_CHALLENGE_SIZE = 150_000  # une page de vérification est toujours légère
SITEMAP_GUESSES = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml",
                   "/sitemap.xml.gz", "/sitemaps/sitemap.xml"]
MAX_DISCOVERED = 5000  # liens nouveaux mémorisés par passe (mode « liens »)
# Adresses qui ressemblent à une fiche produit : visitées en priorité.
PRODUCT_URL = re.compile(r"/p/|/dp/|produit|product|/fiche|/article|\.html?$|\.aspx$|[-_/]\d{5,}", re.I)


@dataclass
class SiteState:
    mode: str = ""  # "shopify", "woocommerce", "sitemap", "liens"
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
    note: str = ""  # diagnostic lisible quand aucun produit n'est trouvé
    blocked: bool = False
    requests: int = 0
    protection: str = ""  # anti-robot détecté (DataDome, Cloudflare…)
    first_page: tuple[str, int, int] | None = None  # (url, taille, nb de liens)
    http_errors: dict[int, int] = field(default_factory=dict)  # code -> nb


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
        except HttpError as e:
            self._on_http_error(e)
            raise
        protection = None if binary else _challenge(out)
        if protection:
            self.result.protection = protection
            self._blocked_hits += 1
            if self._blocked_hits >= 2:
                self.result.blocked = True
                raise _Blocked(f"page anti-robot {protection}")
            raise HttpError(403, url, f"page anti-robot {protection}")
        self._blocked_hits = 0
        return out

    def _on_http_error(self, e: HttpError) -> None:
        self.result.http_errors[e.status] = self.result.http_errors.get(e.status, 0) + 1
        if e.status in BLOCK_STATUSES:
            self._blocked_hits += 1
            if self._blocked_hits >= 3:
                self.result.blocked = True
                raise _Blocked(f"HTTP {e.status} répétés (protection anti-robots)") from None

    def _allowed(self, url: str) -> bool:
        return self.robots.can_fetch("*", url)

    # -- étapes --------------------------------------------------------------
    def _load_robots(self) -> list[str]:
        try:
            txt = self._get(self.base + "/robots.txt", counted=False)
        except HttpError as e:
            if self.result.protection:
                raise _Blocked(f"page anti-robot {self.result.protection} dès le robots.txt") from None
            if e.status in BLOCK_STATUSES:
                raise _Blocked(f"robots.txt refusé (HTTP {e.status})") from None
            txt = ""  # pas de robots.txt : tout est permis
        if txt.lstrip().startswith("<"):
            txt = ""  # page HTML à la place du robots.txt : ignorée
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
        # Plan non déclaré dans robots.txt : on essaie les emplacements courants,
        # jusqu'au premier qui répond.
        guesses = [] if declared else [self.base + p for p in SITEMAP_GUESSES]
        queue = [(u, "") for u in declared]
        pages: dict[str, str] = {}
        files = ok = seen = 0
        failure = ""
        while (queue or (guesses and not ok)) and files < MAX_SITEMAP_FILES \
                and len(pages) < MAX_PAGES_KNOWN:
            url, _ = queue.pop(0) if queue else (guesses.pop(0), "")
            files += 1
            try:
                # Les fichiers sitemap ne comptent pas dans le quota de pages produit.
                kind, entries = sitemap.parse(self._get(url, binary=True, counted=False))
                ok += 1
            except HttpError as e:
                failure = f"HTTP {e.status} sur {url}"
                continue
            except (ValueError, OSError, EOFError, ET.ParseError) as e:
                failure = f"fichier illisible ({type(e).__name__}) : {url}"
                continue
            guesses.clear()
            if kind == "index":
                queue += sitemap.pick_children(entries, self.site.path_prefix)
            else:
                for loc, lastmod in entries:
                    seen += 1
                    if sitemap.keep_url(loc, self.site.domain, self.site.path_prefix) \
                            and self._allowed(loc):
                        pages[loc] = lastmod
        if pages:
            self.result.pages = sorted(pages.items(), key=lambda kv: kv[1], reverse=True)
        elif not ok:
            self.result.note = f"plan du site inaccessible ({failure or 'aucun déclaré'})"
        elif seen:
            self.result.note = (f"plan du site lu ({seen} adresses) mais aucune autorisée "
                                "ou sur le bon domaine")
        else:
            self.result.note = "plan du site vide"

    def _keep_link(self, url: str) -> bool:
        return sitemap.keep_url(url, self.site.domain, self.site.path_prefix) and self._allowed(url)

    def _check_pages(self, urls: list[str], discover: bool = False) -> None:
        """Lit les pages ; en mode « liens », suit aussi les liens trouvés."""
        queue = list(dict.fromkeys(urls))
        seen = set(queue)
        new_links: dict[str, str] = {}
        try:
            while queue:
                url = queue.pop(0)
                if not self._allowed(url):
                    self.result.checked[url] = False
                    continue
                try:
                    html = self._get(url)
                except HttpError as e:
                    if e.status in (404, 410):
                        self.result.checked[url] = False  # page disparue : on l'oublie
                    continue
                found, links = parse_page(html, url, self.site.sellers, self.source)
                if self.result.first_page is None:
                    self.result.first_page = (url, len(html), len(set(links)))
                self.result.checked[url] = bool(found)
                self.result.listings += found
                if not discover:
                    continue
                fresh = [l for l in dict.fromkeys(links) if l not in seen and self._keep_link(l)]
                for l in fresh:
                    seen.add(l)
                    if len(new_links) < MAX_DISCOVERED:
                        new_links[l] = ""
                # Fiches produit d'abord, le reste (catégories…) ensuite.
                queue = ([l for l in fresh if PRODUCT_URL.search(l)] + queue
                         + [l for l in fresh if not PRODUCT_URL.search(l)])
        finally:
            if new_links:
                known = dict(self.result.pages or [])
                known.update({u: m for u, m in new_links.items() if u not in known})
                self.result.pages = list(known.items())

    def _diagnose(self) -> None:
        if self.result.listings or self.result.error:
            return
        parts = [self.result.note] if self.result.note else []
        read = sum(1 for _ in self.result.checked)
        if read:
            parts.append(f"{read} pages lues sans prix exploitable")
        if self.result.protection:
            parts.append(f"protection anti-robot {self.result.protection} détectée")
        if self.result.first_page and read <= 3:
            url, size, links = self.result.first_page
            parts.append(f"1re page : {size // 1024} Ko, {links} liens")
        if self.result.http_errors:
            parts.append("erreurs " + ", ".join(f"HTTP {c} x{n}"
                                                for c, n in sorted(self.result.http_errors.items())))
        self.result.note = " ; ".join(parts) or "aucune page à lire pour l'instant"

    def run(self, to_check: list[str]) -> SiteResult:
        try:
            declared = self._load_robots()
            if not self.result.mode:
                self.result.mode = self._detect_mode()
            if self.result.mode in ("shopify", "woocommerce"):
                self._crawl_feed()
            else:
                self._check_pages([u for u in self.site.start_urls])
                if self.result.mode == "sitemap" and \
                        time.time() - self.state.sitemap_at > SITEMAP_REFRESH:
                    self._refresh_sitemap(declared)
                    if not to_check and self.result.pages:
                        to_check = [u for u, _ in self.result.pages]
                if not to_check and not self.result.pages:
                    # Plan B : pas de plan du site exploitable, on suit les liens
                    # depuis la page d'accueil comme le ferait un visiteur.
                    self.result.mode = "liens"
                if self.result.mode == "liens":
                    # L'accueil est relu à chaque passe : c'est lui qui donne les
                    # nouveautés et les liens vers les rayons.
                    to_check = [self.base + "/"] + [u for u in to_check if u != self.base + "/"]
                self._check_pages(to_check, discover=self.result.mode == "liens")
        except _BudgetExhausted:
            pass
        except _Blocked as e:
            self.result.blocked = True
            self.result.error = str(e)
        except Exception as e:  # site en panne, format inattendu…
            self.result.error = f"{type(e).__name__}: {e}"
        self._diagnose()
        return self.result


def _challenge(html: str) -> str | None:
    if len(html) > MAX_CHALLENGE_SIZE:
        return None
    for pattern, name in CHALLENGES:
        if pattern.search(html):
            return name
    return None


class _BudgetExhausted(Exception):
    pass


class _Blocked(Exception):
    pass

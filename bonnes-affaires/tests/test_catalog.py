import gzip
import json
import unittest

from dealbot.analyzer import analyze_catalog
from dealbot.catalog import feeds, sitemap
from dealbot.catalog.crawler import Crawler, SiteState
from dealbot.config import Settings, Site, Trust, load_sites
from dealbot.http import HttpError
from dealbot.models import Listing
from dealbot.runner import run_catalog
from dealbot.sources.sites import extract_listings
from dealbot.storage import Store
from dealbot.trust import untrusted_reason


def product_page(name, price, gtin="3700000000001", seller=None, sku=None):
    offer = {"@type": "Offer", "price": price, "priceCurrency": "EUR"}
    if seller:
        offer["seller"] = {"@type": "Organization", "name": seller}
    node = {"@type": "Product", "name": name, "gtin13": gtin, "sku": sku or name, "offers": offer}
    return f'<script type="application/ld+json">{json.dumps(node)}</script>'


class FakeSession:
    """Remplace Internet : {url: contenu | code HTTP d'erreur}."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _lookup(self, url, params):
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        self.calls.append(url)
        value = self.routes.get(url, 404)
        if isinstance(value, int):
            raise HttpError(value, url)
        return value

    def request(self, url, params=None, **kw):
        v = self._lookup(url, params)
        return v.decode() if isinstance(v, bytes) else v

    def request_bytes(self, url, params=None, **kw):
        v = self._lookup(url, params)
        return v if isinstance(v, bytes) else v.encode()


SITEMAP_INDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.shop.fr/sitemap-blog.xml</loc></sitemap>
  <sitemap><loc>https://www.shop.fr/sitemap-products-1.xml.gz</loc></sitemap>
</sitemapindex>"""

SITEMAP_PRODUCTS = gzip.compress(b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.shop.fr/p/tv</loc><lastmod>2026-10-01</lastmod></url>
  <url><loc>https://www.shop.fr/p/casque</loc><lastmod>2026-10-05</lastmod></url>
  <url><loc>https://www.shop.fr/private/x</loc></url>
  <url><loc>https://autre-site.fr/p/y</loc></url>
  <url><loc>https://www.shop.fr/img/photo.jpg</loc></url>
</urlset>""")


def shop_routes(tv_price=999):
    return {
        "https://www.shop.fr/robots.txt":
            "User-agent: *\nDisallow: /private/\nSitemap: https://www.shop.fr/sitemap.xml\n",
        "https://www.shop.fr/sitemap.xml": SITEMAP_INDEX,
        "https://www.shop.fr/sitemap-products-1.xml.gz": SITEMAP_PRODUCTS,
        "https://www.shop.fr/p/tv": product_page("TV OLED 55", tv_price, gtin="8806094000001"),
        "https://www.shop.fr/p/casque": product_page("Casque", 199, seller="Revendeur X"),
    }


SHOP = Site(name="Shop", domain="www.shop.fr", kind="marketplace", sellers=["Shop"])


class SitemapTest(unittest.TestCase):
    def test_parse_and_pick_product_sitemaps(self):
        kind, entries = sitemap.parse(SITEMAP_INDEX)
        self.assertEqual(kind, "index")
        self.assertEqual([u for u, _ in sitemap.pick_children(entries)],
                         ["https://www.shop.fr/sitemap-products-1.xml.gz"])
        kind, entries = sitemap.parse(SITEMAP_PRODUCTS)
        self.assertEqual((kind, len(entries)), ("urlset", 5))

    def test_keep_url(self):
        self.assertTrue(sitemap.keep_url("https://shop.fr/p/1", "www.shop.fr"))
        self.assertFalse(sitemap.keep_url("https://other.fr/p/1", "www.shop.fr"))
        self.assertFalse(sitemap.keep_url("https://www.ikea.com/de/de/p/1", "www.ikea.com", "/fr/fr/"))
        self.assertTrue(sitemap.keep_url("https://www.ikea.com/fr/fr/p/1", "www.ikea.com", "/fr/fr/"))


class CrawlerTest(unittest.TestCase):
    def test_sitemap_crawl_respects_robots_and_sellers(self):
        r = Crawler(SHOP, SiteState(), budget=50, session=FakeSession(shop_routes())).run([])
        self.assertEqual(r.error, "")
        self.assertEqual(r.mode, "sitemap")
        # Pages triées par date de modification, hors domaine / images / robots exclus.
        self.assertEqual([u for u, _ in r.pages], ["https://www.shop.fr/p/casque", "https://www.shop.fr/p/tv"])
        # Le casque n'est vendu que par un revendeur tiers : ignoré.
        self.assertEqual([l.title for l in r.listings], ["TV OLED 55"])
        self.assertEqual(r.listings[0].gtin, "8806094000001")
        self.assertEqual(r.checked, {"https://www.shop.fr/p/casque": False, "https://www.shop.fr/p/tv": True})

    def test_budget_limits_pages(self):
        r = Crawler(SHOP, SiteState(), budget=2, session=FakeSession(shop_routes())).run([])
        # 2 sondes (Shopify, WooCommerce) consomment le budget : aucune page produit.
        self.assertEqual(r.checked, {})
        self.assertIsNotNone(r.pages)  # le sitemap, lui, ne compte pas

    def test_blocked_site(self):
        routes = {"https://www.shop.fr/robots.txt": 403}
        r = Crawler(SHOP, SiteState(), budget=50, session=FakeSession(routes)).run([])
        self.assertTrue(r.blocked)

    def test_shopify_feed(self):
        site = Site(name="Marque", domain="www.marque.fr")
        page1 = {"products": [{"title": "Sac", "handle": "sac", "images": [{"src": "i.jpg"}],
                               "variants": [{"id": 11, "title": "Noir", "price": "89.00",
                                             "available": True, "barcode": "3760000000012"},
                                            {"id": 12, "title": "Rouge", "price": "89.00",
                                             "available": False}]}]}
        routes = {
            "https://www.marque.fr/robots.txt": "",
            "https://www.marque.fr/products.json?limit=1": json.dumps(page1),
            "https://www.marque.fr/products.json?limit=250&page=1": json.dumps(page1),
            "https://www.marque.fr/products.json?limit=250&page=2": json.dumps({"products": []}),
        }
        r = Crawler(site, SiteState(), budget=10, session=FakeSession(routes)).run([])
        self.assertEqual(r.mode, "shopify")
        [l] = r.listings
        self.assertEqual((l.title, l.price, l.gtin), ("Sac - Noir", 89.0, "3760000000012"))
        self.assertEqual(r.cursor, 1)  # fin du catalogue -> on reprendra au début

    def test_woocommerce_parse(self):
        [l] = feeds.parse_woocommerce([{"id": 5, "name": "Lampe", "permalink": "https://b.fr/lampe",
                                        "is_in_stock": True,
                                        "prices": {"price": "4990", "currency_code": "EUR",
                                                   "currency_minor_unit": 2}}], "site:b.fr")
        self.assertEqual(l.price, 49.9)


class FallbackTest(unittest.TestCase):
    def test_follows_links_when_no_sitemap(self):
        site = Site(name="Boutique", domain="www.b.fr")
        home = ('<a href="/rayon/tv">TV</a> <a href="https://www.b.fr/tv-oled-55-123456.html">x</a>'
                '<a href="https://ailleurs.fr/p/1">pub</a> <a href="/compte/login">c</a>')
        routes = {
            "https://www.b.fr/robots.txt": "User-agent: *\nDisallow: /compte/\n",
            "https://www.b.fr/sitemap.xml": 404,
            "https://www.b.fr/": home,
            "https://www.b.fr/tv-oled-55-123456.html": product_page("TV OLED 55", 899),
            "https://www.b.fr/rayon/tv": '<a href="/tv-qled-65-654321.html">y</a>',
            "https://www.b.fr/tv-qled-65-654321.html": product_page("TV QLED 65", 1099, gtin="3700000000002"),
        }
        session = FakeSession(routes)
        r = Crawler(site, SiteState(mode="sitemap"), budget=20, session=session).run([])
        self.assertEqual(r.mode, "liens")
        self.assertEqual(sorted(l.title for l in r.listings), ["TV OLED 55", "TV QLED 65"])
        # La fiche produit passe avant la page rayon ; ni lien externe ni page interdite.
        visited = [u for u in session.calls if u.startswith("https://www.b.fr/") and "robots" not in u
                   and "sitemap" not in u]
        self.assertEqual(visited[:2], ["https://www.b.fr/", "https://www.b.fr/tv-oled-55-123456.html"])
        self.assertNotIn("https://www.b.fr/compte/login", session.calls)
        self.assertNotIn("https://ailleurs.fr/p/1", [u for u, _ in r.pages])

    def test_diagnostic_when_nothing_found(self):
        site = Site(name="Vide", domain="www.v.fr")
        routes = {"https://www.v.fr/robots.txt": "", "https://www.v.fr/": "<p>rien</p>"}
        r = Crawler(site, SiteState(mode="sitemap"), budget=10, session=FakeSession(routes)).run([])
        self.assertIn("plan du site inaccessible (HTTP 404", r.note)
        self.assertIn("1 pages lues sans prix", r.note)

    def test_microdata_fallback(self):
        page = ('<title>Aspirateur X | Boutique</title><h1 itemprop="name" content="Aspirateur X"></h1>'
                '<span itemprop="price" content="249.90"></span><meta itemprop="gtin13" content="3760000000011">')
        [l] = extract_listings(page, "https://www.b.fr/aspi")
        self.assertEqual((l.title, l.price, l.gtin), ("Aspirateur X", 249.9, "3760000000011"))

    def test_microdata_ignored_on_list_pages(self):
        page = '<span itemprop="price" content="10"></span><span itemprop="price" content="20"></span><title>Rayon</title>'
        self.assertEqual(extract_listings(page, "https://www.b.fr/rayon"), [])


class SellerFilterTest(unittest.TestCase):
    def test_marketplace_keeps_only_allowed_seller(self):
        page = product_page("TV", 500, seller="Cdiscount")
        self.assertEqual(len(extract_listings(page, "https://www.cdiscount.com/tv", ["Cdiscount"])), 1)
        page = product_page("TV", 300, seller="SuperDeals Ltd")
        self.assertEqual(extract_listings(page, "https://www.cdiscount.com/tv", ["Cdiscount"]), [])

    def test_aggregate_offer_picks_allowed_seller(self):
        node = {"@type": "Product", "name": "TV", "sku": "1", "offers": {
            "@type": "AggregateOffer", "lowPrice": 300, "offers": [
                {"@type": "Offer", "price": 300, "seller": {"name": "Inconnu"}},
                {"@type": "Offer", "price": 480, "seller": {"name": "Fnac.com"}}]}}
        page = f'<script type="application/ld+json">{json.dumps(node)}</script>'
        [l] = extract_listings(page, "https://www.fnac.com/tv", ["Fnac"])
        self.assertEqual((l.price, l.seller, l.seller_checked), (480, "Fnac.com", True))

    def test_og_fallback_disabled_on_filtered_marketplace(self):
        page = (product_page("TV", 300, seller="Inconnu")
                + '<meta property="og:title" content="TV"><meta property="product:price:amount" content="300">')
        self.assertEqual(extract_listings(page, "https://www.fnac.com/tv", ["Fnac"]), [])


class CatalogAnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.settings = Settings()
        self.now = 1_000_000_000

    def L(self, source, price, gtin="8806094000001"):
        return Listing(f"site:{source}", "tv", "TV OLED 55", price, "EUR", f"https://{source}/tv", gtin=gtin)

    def test_cross_site_comparison_by_barcode(self):
        for shop, price in [("a.fr", 1000), ("b.fr", 980), ("c.fr", 1020)]:
            self.assertEqual(analyze_catalog([self.L(shop, price)], self.store, self.settings, now=self.now), [])
        [deal] = analyze_catalog([self.L("d.fr", 299)], self.store, self.settings, now=self.now)
        self.assertEqual(deal.kind, "erreur_prix")
        self.assertIn("3 autres sites", deal.reason)
        self.assertIn("b.fr à 980.00", deal.reason)

    def test_needs_enough_other_sites(self):
        analyze_catalog([self.L("a.fr", 1000)], self.store, self.settings, now=self.now)
        self.assertEqual(analyze_catalog([self.L("d.fr", 299)], self.store, self.settings, now=self.now), [])

    def test_price_drop_and_min_price(self):
        analyze_catalog([self.L("a.fr", 800, gtin="")], self.store, self.settings, now=self.now)
        [deal] = analyze_catalog([self.L("a.fr", 500, gtin="")], self.store, self.settings, now=self.now + 60)
        self.assertEqual(deal.kind, "baisse_prix")
        cheap = [self.L("x.fr", 10, gtin=""), self.L("x.fr", 5, gtin="")]
        self.assertEqual(analyze_catalog(cheap, self.store, self.settings, now=self.now), [])

    def test_run_catalog_end_to_end(self):
        s = Settings()
        s.catalog.sites = [SHOP]
        sent = []

        class Collect:
            def send(self, deal):
                sent.append(deal)

        routes = shop_routes(999)
        run_catalog(s, self.store, [Collect()], session_factory=lambda: FakeSession(routes))
        self.assertEqual(sent, [])
        routes["https://www.shop.fr/p/tv"] = product_page("TV OLED 55", 199, gtin="8806094000001")
        run_catalog(s, self.store, [Collect()], session_factory=lambda: FakeSession(routes))
        self.assertEqual([(d.kind, d.listing.total) for d in sent], [("erreur_prix", 199)])
        # Un site bloqué est mis en pause.
        routes["https://www.shop.fr/robots.txt"] = 403
        run_catalog(s, self.store, [Collect()], session_factory=lambda: FakeSession(routes))
        self.assertGreater(self.store.site_row("www.shop.fr")["blocked_until"], 0)


class TrustTest(unittest.TestCase):
    def listing(self, source, rating, reviews, pro=True):
        return Listing(source, "1", "x", 10, "EUR", "u", seller="bob",
                       seller_rating=rating, seller_reviews=reviews, seller_pro=pro)

    def test_ebay(self):
        t = Trust()
        self.assertIsNone(untrusted_reason(self.listing("ebay", 99.5 / 20, 3000), t))
        self.assertIn("%", untrusted_reason(self.listing("ebay", 95 / 20, 3000), t))
        self.assertIn("évaluations", untrusted_reason(self.listing("ebay", 5, 12), t))
        self.assertIsNotNone(untrusted_reason(self.listing("ebay", None, None), t))

    def test_ebay_private_sellers_always_refused(self):
        t = Trust()
        self.assertIn("particulier", untrusted_reason(self.listing("ebay", 5, 99999, pro=False), t))
        self.assertIn("inconnu", untrusted_reason(self.listing("ebay", 5, 99999, pro=None), t))

    def test_shops_not_concerned(self):
        self.assertIsNone(untrusted_reason(self.listing("site:fnac.com", None, None), Trust()))


class SitesListTest(unittest.TestCase):
    def test_bundled_list_is_valid(self):
        sites = load_sites()
        self.assertGreaterEqual(len(sites), 40)
        domains = [s.domain for s in sites]
        self.assertEqual(len(domains), len(set(domains)))
        for s in sites:
            self.assertIn(s.kind, ("enseigne", "marketplace"))
        names = {s.domain for s in sites}
        self.assertNotIn("www.leboncoin.fr", names)  # pas de plateforme entre particuliers


if __name__ == "__main__":
    unittest.main()
